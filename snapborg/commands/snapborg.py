#!/usr/bin/env python3

"""
Synchronize snapper snapshots to a borg repository

released under the GNU GPLv3 or any later version.
(c) 2020 Marinus Enzinger <marinus@enzingerm.de>


config usually in /etc/snapborg.yaml
"""


import argparse
import re
import subprocess
import sys
from datetime import datetime, timedelta

import yaml

from ..borg import BorgRepo
from ..retention import get_retained_snapshots
from ..snapper import SnapperConfig
from ..util import selective_merge

DEFAULT_CONFIG = {
    "configs": []
}

DEFAULT_CONFIG_PER_REPO = {
    "exclude_patterns": [],
    "fault_tolerant_mode": False,
    "last_backup_max_age": "0d"
}


def main():
    """
    Entry point for snapborg
    """

    cli = argparse.ArgumentParser()
    cli.add_argument("--cfg", default="/etc/snapborg.yaml", help="Snapborg config file location")
    cli.add_argument("--dryrun", action="store_true", help="Don't actually execute commands")
    cli.add_argument("--bind-mount", action="store_true",
                     help="Bind mount snapshots so that file paths are consistent, which means caching works much "
                          "better. Requires running as root.")
    cli.add_argument("--snapper-config", default=None, dest="snapper_config",
                     help="The name of a snapper config to operate on")
    subp = cli.add_subparsers(dest="mode", required=True)

    subp.add_parser("prune", help="Prune the borg archives using the retention settings from the "
                    "snapborg config file")
    subp.add_parser("list", help="List all snapper snapshots including their creation date and "
                    "whether they have already been backed up by snapborg")
    backupcli = subp.add_parser(
        "backup", help="Backup all the snapper snapshots which are not already "
        "backed up")
    backupcli.add_argument(
        "--recreate", action="store_true", dest="recreate",
        help="Delete possibly existing borg archives and recreate them from scratch")
    backupcli.add_argument(
        "--no-prune", action="store_true", help="Ignore retention policy and don't prune old backups")
    subp.add_parser("init")
    subp.add_parser("clean-snapper", help="Clean snapper snapshots from all snapborg specific "
                    "user data")

    args = cli.parse_args()

    with open(args.cfg, 'r') as stream:
        cfg = selective_merge(yaml.safe_load(stream), DEFAULT_CONFIG)
    configs = get_configs(cfg, args.snapper_config)

    if args.mode == "init":
        init(cfg, snapper_configs=configs, dryrun=args.dryrun)

    elif args.mode == "prune":
        prune(cfg, snapper_configs=configs, dryrun=args.dryrun)

    elif args.mode == "backup":
        backup(cfg, snapper_configs=configs, recreate=args.recreate,
               prune_old_backups=not args.no_prune, dryrun=args.dryrun,
               bind_mount=args.bind_mount)

    elif args.mode == "list":
        list_snapshots(cfg, configs=configs)

    elif args.mode == "clean-snapper":
        clean_snapper(cfg, snapper_configs=configs, dryrun=args.dryrun)

    else:
        raise Exception("Unknown program mode")


def list_snapshots(cfg, configs):
    print("Listing snapper snapshots:")
    for config in configs:
        snapper_config = SnapperConfig.get(config["name"])
        print(f"\tConfig {snapper_config.name} for subvol {snapper_config.get_path()}:")
        snapshots = snapper_config.get_snapshots()
        for s in snapshots:
            print(
                f"\t\tSnapshot {s.get_number()} from {s.get_date()} is backed up: {s.is_backed_up()}")


def get_configs(cfg, config_arg=None):
    """
    Check the snapper configs in the snapborg config file and return a list of the
    configs to operate on.
    """
    configs = cfg["configs"]
    # every config must have a name
    if any(not config["name"] for config in configs):
        raise Exception("Snapper config name must be given for every config section!")

    # duplicate configs are not allowed
    if len(set(config["name"] for config in configs)) != len(configs):
        raise Exception("Duplicate config sections found!")

    configs = [selective_merge(c, DEFAULT_CONFIG_PER_REPO) for c in configs]
    for c in configs:
        res = re.fullmatch("(\\d+)(d|h)", c["last_backup_max_age"])
        if not res:
            raise Exception(
                "last_backup_max_age must be given as either days (e.g. '5d') or hours (e.g. '6h')")
        val = int(res.group(1))
        c["last_backup_max_age"] = timedelta(hours=val if res.group(2) == "h" else val * 24)

    if config_arg:
        configs = [ c for c in configs if c["name"] == config_arg ]
        if len(configs) == 0:
            raise ValueError(f"no such config \"{config_arg}\"")
    return configs



def backup(cfg, snapper_configs, recreate, prune_old_backups, dryrun, bind_mount):
    """
    Backup all given snapper configs, optionally recreating the archives
    """
    status_map = {}
    for config in snapper_configs:
        try:
            backup_config(config, recreate, dryrun, bind_mount)
            status_map[config["name"]] = True
        except Exception as e:
            status_map[config["name"]] = e
    print("\nBackup results:")
    has_error = False
    for config_name, status in status_map.items():
        if status is True:
            print(f"OK     {config_name}")
        else:
            has_error = True
            print(f"FAILED {config_name}: {status}")

    if has_error:
        raise Exception("Snapborg failed!")
    elif prune_old_backups:
        prune(cfg, snapper_configs, dryrun)


def backup_config(config, recreate, dryrun, bind_mount):
    """
    Backup a single snapper config
    """
    name = config["name"]
    print(f"Backing up snapshots for snapper config '{name}'...")
    snapper_config = None
    snapshots = None

    try:
        snapper_config = SnapperConfig.get(name)
        # when we have the config, extract the snapshots which are not yet backed up
        snapshots = snapper_config.get_snapshots()
        if len(snapshots) == 0:
            print("No snapshots from snapper found!")
            return
    except subprocess.SubprocessError:
        raise Exception(f"Failed to get snapper config {name}!")

    repo = BorgRepo.create_from_config(config)
    # now determine which snapshots need to be backed up
    retention_config = repo.get_retention_config()
    candidates = [
        snapshot
        for snapshot in get_retained_snapshots(
            snapshots, lambda s: s.get_date(),
            **retention_config) if(not snapshot.is_backed_up() or recreate)
    ]

    mount_path = f'/var/run/snapborg/{name}' if bind_mount else None

    with snapper_config.prevent_cleanup(snapshots=candidates, dryrun=dryrun):
        results = [ backup_candidate(snapper_config, repo, candidate, recreate,
                                     config["exclude_patterns"], dryrun=dryrun,
                                     mount_path=mount_path)
                for candidate in candidates ]
    has_error = any(not result for result in results)

    # possibly accept any error during backup only if fault tolerant mode is active!
    if has_error and not config["fault_tolerant_mode"]:
        raise Exception(f"Error(s) while transferring backups for {snapper_config.name}!")

    if config["last_backup_max_age"].total_seconds() > 0:
        # fail if the creation date of the newest snapshot successfully backed up is too old
        snapshots = snapper_config.get_snapshots()
        backed_up = [ s for s in snapshots if s.is_backed_up() ]
        if len(snapshots) > 0 and len(backed_up) == 0:
            raise Exception("No snapshots have been transferred to the borg repo!")
        newest_backed_up = max(
            backed_up,
            key=lambda x: x.get_date())
        if newest_backed_up.get_date() + config["last_backup_max_age"] < datetime.now():
            raise Exception(
                f"Last successful backup for config {snapper_config.name} is from "
                f"{newest_backed_up.get_date().isoformat()} and thus too old!")


def backup_candidate(snapper_config, borg_repo, candidate, recreate,
                     exclude_patterns, dryrun=False, mount_path=None):
    print(f"Backing up snapshot number {candidate.get_number()} "
          f"from {candidate.get_date().isoformat()}...")
    path_to_backup = candidate.get_path()
    backup_name = f"{snapper_config.name}-{candidate.get_number()}-{candidate.get_date().isoformat()}"
    try:
        if recreate:
            borg_repo.delete(backup_name, dryrun=dryrun)
            candidate.purge_userdata(dryrun=dryrun)
        borg_repo.backup(backup_name, path_to_backup, timestamp=candidate.get_date(),
                         exclude_patterns=exclude_patterns, dryrun=dryrun, mount_path=mount_path)
        candidate.set_backed_up(dryrun=dryrun)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error backing up snapshot number {candidate.get_number()}!\n\t{e}")
        return False


def prune(cfg, snapper_configs, dryrun):
    for config in snapper_configs:
        BorgRepo.create_from_config(config).prune(dryrun=dryrun)


def init(cfg, snapper_configs, dryrun):
    """
    Create new borg archives in none or in repokey mode
    """
    for config in snapper_configs:
        BorgRepo.create_from_config(config).init(dryrun=dryrun)


def clean_snapper(cfg, snapper_configs, dryrun):
    """
    Clean snapper userdata from snapborg specific settings
    """
    for config in snapper_configs:
        snapper_config = SnapperConfig.get(config["name"])
        snapshots = snapper_config.get_snapshots()
        for s in snapshots:
            s.purge_userdata(dryrun=dryrun)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Snapborg failed: {e}!")
        sys.exit(1)
