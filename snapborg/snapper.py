import json
import subprocess
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Set, Optional, Union

from packaging import version
from .config import LEGACY_REPO_NAME, RepoConfig
from .exceptions import SnapperExecutionException, SnapperTooOldException

SNAPBORG_BACKUP_KEY_LEGACY = "snapborg_backup"
SNAPBORG_BACKUP_KEY = "snapborg_backup_repos"


def check_snapper():
    """
    Snapper version should be >= 0.8.6 to be able to use machine readable output
    """
    try:
        output = subprocess.check_output(["snapper", "--version"]).decode()
    except subprocess.CalledProcessError as e:
        raise SnapperExecutionException from e
    line = [l for l in output.splitlines() if l.startswith("snapper")][0]
    snapper_version = line.split(" ")[1]
    if version.parse(snapper_version) < version.parse("0.8.6"):
        raise SnapperTooOldException(f"Snapper version {snapper_version} is too old, must be > 0.8.6!")


def run_snapper(args, config: Optional[str] = None, dryrun=False):
    """
    Run a snapper command, optionally for a given config, and return
    the parsed JSON output
    """
    try:
        run_snapper.snapper_version_ok
    except AttributeError:
        check_snapper()
        run_snapper.snapper_version_ok = True
    args_new = [
        "snapper",
        *([] if not config else ["-c", config]),
        "--jsonout",
        *args
    ]
    if dryrun:
        print(f"$ {' '.join(args_new)}")
        return None
    else:
        try:
            output = subprocess.check_output(args_new).decode().strip()
        except subprocess.CalledProcessError as e:
            raise SnapperExecutionException from e
        return json.loads(output) if output != "" else None


class SnapperConfig:
    def __init__(self, name: str, settings):
        self.name = name
        self.settings = settings
        self._snapshots = None

    def is_timeline_enabled(self):
        return self.settings["TIMELINE_CREATE"] == "yes"

    @property
    def path(self):
        return self.settings["SUBVOLUME"]

    @property
    def is_root(self):
        return self.path == '/'

    def get_snapshots(self):
        if not self._snapshots:
            self._snapshots = [
                SnapperSnapshot(self, info)
                for info in run_snapper(["list", "--disable-used-space"], self.name)[self.name]
                # exclude the currently "live" snapshot
                if info["number"] != 0
            ]
        return self._snapshots
    
    def get_archive_name(self, snapshot: 'SnapperSnapshot') -> str:
        return f"{self.name}-{snapshot.number}-{snapshot.date.isoformat()}"

    @classmethod
    def get(cls, config_name: str):
        return cls(config_name, run_snapper(["get-config"], config_name))
    
    @contextmanager
    def prevent_cleanup(self, snapshots=None, dryrun=False):
        """
        Return a context manager for this snapper config where each snapshot
        is prevented from being cleaned up by the timeline cleanup process
        """
        if snapshots is None:
            snapshots = self.get_snapshots()

        for s in snapshots:
            s.prevent_cleanup(dryrun=dryrun)
        
        try:
            yield self
        finally:
            for s in snapshots:
                s.restore_cleanup_state(dryrun=dryrun)


class SnapperSnapshot:
    def __init__(self, config: SnapperConfig, info):
        self.config = config
        self._is_backed_up: Set[str] = set()
        self.info = info
        snapborg_backup_legacy = (info["userdata"] or dict()).get(SNAPBORG_BACKUP_KEY_LEGACY)
        snapborg_backup = (info["userdata"] or dict()).get(SNAPBORG_BACKUP_KEY)
        if snapborg_backup:
            for repo in snapborg_backup.lstrip(" [").rstrip(" ]").split(";"):
                self._is_backed_up.add(repo.strip())
        elif snapborg_backup_legacy == 'true':
            self._is_backed_up.add(LEGACY_REPO_NAME)
        self._cleanup = info["cleanup"]

    @property
    def date(self):
        return datetime.fromisoformat(self.info["date"])

    @property
    def date_utc(self):
        local_time_naive = datetime.fromisoformat(self.info["date"])
        local_time_aware = local_time_naive.astimezone()
        utc_time = local_time_aware.astimezone(timezone.utc)
        return utc_time

    @property
    def path(self):
        return f"{self.config.path}/.snapshots/{self.number}/snapshot"

    def is_backed_up(self, repo: Union[str, RepoConfig]) -> bool:
        repo = repo.name if isinstance(repo, RepoConfig) else repo
        return repo in self._is_backed_up

    @property
    def number(self):
        return self.info["number"]

    def purge_userdata(self, dryrun=False):
        run_snapper(
            ["modify", "--userdata", f"{SNAPBORG_BACKUP_KEY}=,{SNAPBORG_BACKUP_KEY_LEGACY}=", f"{self.number}"],
            self.config.name, dryrun=dryrun)

    def set_backup_status(self, repo: Union[str, RepoConfig], status: bool, dryrun=False):
        repo = repo.name if isinstance(repo, RepoConfig) else repo
        if status:
            self._is_backed_up.add(repo)
        else:
            self._is_backed_up.discard(repo)
        userdata = '[' + ';'.join(self._is_backed_up) + ']'
        legacy_userdata = (
                f",{SNAPBORG_BACKUP_KEY_LEGACY}=" + 'true' if status else ''
            ) if repo == LEGACY_REPO_NAME else ""

        run_snapper(["modify", "--userdata", f"{SNAPBORG_BACKUP_KEY}={userdata}{legacy_userdata}",
                     f"{self.number}"], self.config.name, dryrun=dryrun)
    

    def prevent_cleanup(self, dryrun=False):
        """
        Prevents this snapshot from being cleaned up
        """

        run_snapper(
            ["modify", "--cleanup-algorithm", "", f"{self.number}"],
            self.config.name, dryrun=dryrun
        )

    def restore_cleanup_state(self, dryrun=False):
        """
        Restores the cleanup algorithm for this snapshot
        """
        run_snapper(
            ["modify", "--cleanup-algorithm", self._cleanup, f"{self.number}"],
            self.config.name, dryrun=dryrun
        )
