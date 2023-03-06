import json
import subprocess
from datetime import datetime
from contextlib import contextmanager
import uuid

from packaging import version

from .util import init_snapborg_logger

LOG = init_snapborg_logger(__name__)

def check_snapper():
    """
    Snapper version should be >= 0.8.6 to be able to use machine readable output
    """
    output = subprocess.check_output(["snapper", "--version"]).decode()
    line = [l for l in output.splitlines() if l.startswith("snapper")][0]
    snapper_version = line.split(" ")[1]
    if version.parse(snapper_version) < version.parse("0.8.6"):
        raise Exception(f"Snapper version {snapper_version} is too old!")


def run_snapper(args, config: str = None, dryrun=False):
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
        LOG.info(args_new)
        return {}
    else:
        output = subprocess.check_output(args_new).decode().strip()
        return json.loads(output) if output != "" else {}


class SnapperConfig:
    def __init__(self, name: str, settings):
        self.name = name
        self.settings = settings
        self._snapshots = None

    def is_timeline_enabled(self):
        return self.settings["TIMELINE_CREATE"] == "yes"

    def get_path(self):
        return self.settings["SUBVOLUME"]

    def get_snapshots(self):
        if not self._snapshots:
            self._snapshots = [
                SnapperSnapshot(self, info)
                for info in run_snapper(["list", "--disable-used-space"], self.name)[self.name]
                # exclude the currently "live" snapshot
                if info["number"] != 0
            ]
        return self._snapshots

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
        self.info = info
        self._cleanup = info["cleanup"]

    def get_date(self):
        return datetime.fromisoformat(self.info["date"])

    def get_path(self):
        return f"{self.config.get_path()}/.snapshots/{self.get_number()}/snapshot"

    def get_number(self):
        return self.info["number"]

    def get_snapborg_id(self):
        return (self.info["userdata"] or dict()).get("snapborg_id")

    def generate_snapborg_id(self, dryrun=False):
        snapshot_uuid = self.get_snapborg_id()
        if snapshot_uuid is None:
            if self.info["userdata"] is None:
                self.info["userdata"] = {}
            snapshot_uuid = uuid.uuid4()
            self.info["userdata"]["snapborg_id"] = snapshot_uuid
            run_snapper(
                [
                    "modify",
                    "--userdata",
                    f"snapborg_id={snapshot_uuid}",
                    f"{self.get_number()}",
                ],
                self.config.name,
                dryrun=dryrun,
            )
        return self.info["userdata"]["snapborg_id"]

    def purge_userdata(self, dryrun=False):
        run_snapper(
            ["modify", "--userdata", "snapborg_id=", f"{self.get_number()}"],
            self.config.name,
            dryrun=dryrun,
        )

    def prevent_cleanup(self, dryrun=False):
        """
        Prevents this snapshot from being cleaned up
        """
        run_snapper(
            ["modify", "--cleanup-algorithm", "", f"{self.get_number()}"],
            self.config.name, dryrun=dryrun
        )

    def restore_cleanup_state(self, dryrun=False):
        """
        Restores the cleanup algorithm for this snapshot
        """
        run_snapper(
            ["modify", "--cleanup-algorithm", self._cleanup, f"{self.get_number()}"],
            self.config.name, dryrun=dryrun
        )
