#!/usr/bin/env python3

"""
Synchronize snapper snapshots to a borg repository

released under the GNU GPLv3 or any later version.
(c) 2020-2025 Marinus Enzinger <marinus@enzingerm.de>


config usually in /etc/snapborg.yaml
"""


import argparse
from dataclasses import asdict
import os
from datetime import datetime
from typing import List, Optional


from ..config import LEGACY_REPO_NAME, SnapborgConfig, load_config, SnapborgSnapperConfig
from ..exceptions import (
    BorgExecutionException,
    InvalidParameterException,
    SnapborgBaseException,
    SnapperExecutionException,
)
from ..results import CommandResult, ResultStatus
from ..borg import BORG_RETURNCODE_ARCHIVE_EXISTS, BorgRepo
from ..retention import get_retained_snapshots
from ..snapper import SnapperConfig, SnapperSnapshot


def run_snapborg():
    """
    Entry point for snapborg
    """

    cli = argparse.ArgumentParser()
    cli.add_argument("--cfg", default="/etc/snapborg.yaml", help="Snapborg config file location")
    cli.add_argument("--dryrun", action="store_true", help="Don't actually execute commands")
    cli.add_argument(
        "--bind-mount",
        action="store_true",
        help="OBSOLETE/has no effect: see --absolute-paths parameter of the `backup` command",
    )
    cli.add_argument(
        "--snapper-config",
        default=None,
        dest="snapper_config",
        help="The name of a snapper config to operate on",
    )
    subp = cli.add_subparsers(dest="mode", required=True)

    subp.add_parser(
        "prune",
        help="Prune the borg archives using the retention settings from the "
        "snapborg config file",
    )
    subp.add_parser(
        "list",
        help="List all snapper snapshots including their creation date and "
        "whether they have already been backed up by snapborg",
    )
    backupcli = subp.add_parser(
        "backup", help="Backup all the snapper snapshots which are not already " "backed up"
    )
    backupcli.add_argument(
        "--absolute-paths",
        action="store_true",
        help="Archive files in the btrfs"
        " subvolume with their absolute paths. Requires running as root (uses bind-mount)."
        "If not given, files are stored with their paths relative to the subvolume root.",
    )
    backupcli.add_argument(
        "--recreate",
        action="store_true",
        dest="recreate",
        help="Delete possibly existing borg archives and recreate them from scratch",
    )
    backupcli.add_argument(
        "--no-prune",
        action="store_true",
        help="Ignore retention policy and don't prune old backups",
    )
    subp.add_parser(
        "clean-snapper", help="Clean snapper snapshots from all snapborg specific " "user data"
    )

    args = cli.parse_args()

    cfg = load_config(args.cfg)
    configs = get_snapper_configs(cfg, args.snapper_config)

    if args.mode == "prune":
        prune(snapper_configs=configs, dryrun=args.dryrun)

    elif args.mode == "backup":
        backup(
            configs,
            recreate=args.recreate,
            prune_old_backups=not args.no_prune,
            dryrun=args.dryrun,
            absolute_paths=args.absolute_paths,
        )

    elif args.mode == "list":
        list_snapshots(configs)

    elif args.mode == "clean-snapper":
        clean_snapper(configs, dryrun=args.dryrun)

    else:
        raise SnapborgBaseException("Unknown program mode")


def list_snapshots(configs: List[SnapborgSnapperConfig]):
    print("Listing snapper snapshots:")
    for config in configs:
        snapper_config = SnapperConfig.get(config.name)
        print(f"Config {snapper_config.name} for subvol {snapper_config.path}:")
        snapshots = snapper_config.get_snapshots()
        for s in snapshots:
            print(
                f"  Snapshot {s.number} from {s.date} is backed up to the following borg repositories:"
            )
            for repo in config.repos:
                print(
                    f"    {repo.name} ({repo.path}): "
                    + ("Yes" if s.is_backed_up(repo.name) else "No")
                )


def backup(
    snapper_configs: List[SnapborgSnapperConfig],
    recreate,
    prune_old_backups,
    dryrun,
    absolute_paths,
):
    """
    Backup all given snapper configs, optionally recreating the archives
    """

    print("Backup started...")
    results = CommandResult.from_children(
        [backup_config(config, recreate, dryrun, absolute_paths) for config in snapper_configs],
        "Backup of snapper config(s): " + ", ".join(s.name for s in snapper_configs),
    )
    print("\nBackup results:")
    print(results.get_output())

    if results.status == ResultStatus.ERR:
        raise SnapborgBaseException()
    elif prune_old_backups:
        prune(snapper_configs, dryrun)


def backup_config(config: SnapborgSnapperConfig, recreate, dryrun, absolute_paths) -> CommandResult:
    """
    Backup a single snapper config
    """
    name = config.name
    print(f"Backing up snapshots for snapper config '{name}'...")

    snapper_config = SnapperConfig.get(name)

    mount_path = None
    if absolute_paths:
        # the dot here leads to borg stripping the path prefix from the archived paths (sets recursion root)
        # see borg "slashdot hack"
        mount_path = os.path.join("/run/snapborg", name, ".")
        if not snapper_config.is_root:
            mount_path = os.path.join(mount_path, os.path.relpath(snapper_config.path, "/"))

    repo_results = [
        backup_to_repo(
            BorgRepo.create_from_config(config, repo_config, dryrun),
            snapper_config,
            recreate,
            dryrun,
            mount_path=mount_path,
        )
        for repo_config in config.repos
    ]

    return CommandResult.from_children(
        repo_results,
        f"Backup of snapper config {config.name}" + (" (recreating archives)" if recreate else ""),
    )


def backup_to_repo(
    repo: BorgRepo,
    snapper_config: SnapperConfig,
    recreate: bool,
    dryrun: bool,
    mount_path: Optional[str] = None,
) -> CommandResult:
    """Backup all needed snapper snapshots to one specific borg repo"""

    print(f"Backing up snapshots to repo {repo.name} ({repo.repo_path})...")
    try:
        # when we have the config, extract the snapshots which are not yet backed up
        snapshots = snapper_config.get_snapshots()
        if len(snapshots) == 0:
            return CommandResult.warn(
                f"No snapshots found for snapper config {snapper_config.name}!"
            )
    except SnapperExecutionException as e:
        return CommandResult.err(
            f"Failed to get snapshots for snapper config {snapper_config.name}: {e}"
        )

    retention_config = asdict(repo.retention_config)
    candidates = [
        snapshot
        for snapshot in get_retained_snapshots(snapshots, lambda s: s.date, **retention_config)
        if (not snapshot.is_backed_up(repo.name) or recreate)
    ]
    if len(candidates) == 0:
        return CommandResult.ok("No new snapshots needed to be backed up!")

    snapshot_results = []
    try:
        with snapper_config.prevent_cleanup(snapshots=candidates, dryrun=dryrun):
            snapshot_results = [
                backup_snapshot(
                    snapper_config, repo, candidate, recreate, dryrun=dryrun, mount_path=mount_path
                )
                for candidate in candidates
            ]
    except SnapperExecutionException as e:
        return CommandResult.err(
            f"Snapper error during handling of cleanup algorithm: {e}", children=snapshot_results
        )

    repo_string = f"{repo.repo_config.name} (at {repo.repo_config.path})"
    if any(it.status == ResultStatus.ERR for it in snapshot_results):
        # check if this borg repo is allowed to fail
        fail_after = repo.repo_config.get_fail_after()
        if fail_after == False:
            return CommandResult.warn(
                f"Backup to optional repo {repo_string}", children=snapshot_results
            )
        elif fail_after == True:
            return CommandResult.err(
                f"Backup to mandatory repo {repo_string}", children=snapshot_results
            )
        else:
            # TODO handle error
            snapshots = snapper_config.get_snapshots()
            backed_up = [s for s in snapshots if s.is_backed_up(repo.name)]
            if len(snapshots) > 0 and len(backed_up) == 0:
                return CommandResult.err(
                    "No snapshots have been transferred to the borg repo yet!",
                    children=snapshot_results,
                )
            newest_backed_up = max(backed_up, key=lambda x: x.date)
            if newest_backed_up.date + fail_after < datetime.now():
                return CommandResult.err(
                    f"Backup to (time limited) optional repo {repo_string}:"
                    "Newest snapshot transferred to the borg repo is older than "
                    f"allowed as per the 'fail_after' directive ({newest_backed_up.date}!",
                    children=snapshot_results,
                )
            else:
                return CommandResult.warn(
                    f"Backup to (time limited) optional repo {repo_string}:"
                    "Errors occured during backup but the most recent snapshot"
                    " is newer than the limit allowed as per the 'fail_after' directive!",
                    children=snapshot_results,
                )

    else:
        # no errors happened
        return CommandResult.from_children(snapshot_results, f"Backup to repo {repo_string}")


def backup_snapshot(
    snapper_config: SnapperConfig,
    borg_repo: BorgRepo,
    snapshot: SnapperSnapshot,
    recreate: bool,
    dryrun=False,
    mount_path=None,
) -> CommandResult:
    """Backup one specific snapper snapshot to one specific borg repository, potentially recreating
    an existing archive"""
    print(
        f"Backing up snapshot number {snapshot.number}, created at "
        f"{snapshot.date.isoformat()}..."
    )
    backup_name = snapper_config.get_archive_name(snapshot)
    try:
        if recreate:
            borg_repo.delete(backup_name)
            snapshot.set_backup_status(borg_repo.name, False, dryrun)
        borg_repo.backup(
            backup_name, snapshot.path, timestamp=snapshot.date_utc, mount_path=mount_path
        )
        snapshot.set_backup_status(borg_repo.name, True, dryrun)
        return CommandResult.ok(f"Successfully backed up snapshot number {snapshot.number}")
    except BorgExecutionException as e:
        if (
            e.returncode == BORG_RETURNCODE_ARCHIVE_EXISTS
            and not borg_repo.repo_config.is_old_config
            and snapshot.is_backed_up(LEGACY_REPO_NAME)
        ):
            # Borg tells us that the archive already exists, we are operating with a new repo_config
            # which has a unique name and the snapshot still has the legacy repo name in the userdate
            # --> It can be assumed that the configuration has been migrated, so the repo name in the
            #     userdata should be updated
            snapshot.set_backup_status(borg_repo.name, True)
            snapshot.set_backup_status(LEGACY_REPO_NAME, False)
            return CommandResult.warn(f"Snapshot {snapshot.number} had already been backed up!")
        return CommandResult.err(
            f"Borg reported an error backing up snapshot number {snapshot.number}: {e}"
        )
    except SnapperExecutionException as e:
        return CommandResult.err(
            f"Borg reported an error backing up snapshot number {snapshot.number}: {e}"
        )


def prune(snapper_configs, dryrun):
    for config in snapper_configs:
        for repo_config in config.repos:
            BorgRepo.create_from_config(config, repo_config, dryrun).prune()


def clean_snapper(snapper_configs: List[SnapborgSnapperConfig], dryrun: bool):
    """
    Clean snapper userdata from snapborg specific settings
    """
    for config in snapper_configs:
        snapper_config = SnapperConfig.get(config.name)
        snapshots = snapper_config.get_snapshots()
        for s in snapshots:
            s.purge_userdata(dryrun=dryrun)


def get_snapper_configs(cfg: SnapborgConfig, config_arg=None) -> List[SnapborgSnapperConfig]:
    """
    Get the snapper configs to operate on based on the possibly given --snapper-config argument
    """

    configs = cfg.configs
    if config_arg:
        configs = [c for c in configs if c.name == config_arg]
        if len(configs) == 0:
            raise InvalidParameterException(f'No such config "{config_arg}"')
    return configs
