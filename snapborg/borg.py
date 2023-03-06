import json
import os
import subprocess
import sys
from subprocess import CalledProcessError

from .util import restrict_keys, selective_merge, init_snapborg_logger

LOG = init_snapborg_logger(__name__)

DEFAULT_REPO_CONFIG = {
    "storage": {
        "encryption": "none",
        "compression": "auto,zstd,4"
    },
    "retention": {
        "keep_last": 1,
        "keep_hourly": 0,
        "keep_daily": 7,
        "keep_weekly": 4,
        "keep_monthly": 3,
        "keep_yearly": 5
    }
}


class BorgRepo:
    def __init__(self, repopath: str, compression: str, retention, encryption="none",
                 passphrase=None):
        self.repopath = repopath
        self.compression = compression
        self.retention = retention
        self.encryption = encryption
        self.passphrase = passphrase
        self.is_interactive = os.isatty(sys.stdout.fileno())

    def init(self, dryrun=False):
        """
        Initialize the borg repository
        """
        # TODO: should we really fail if repo already exists?
        borg_init_invocation = [
            "init",
            "--encryption",
            self.encryption,
            "--make-parent-dirs",
            self.repopath,
        ]
        launch_borg(borg_init_invocation, self.passphrase,
                    log_output=self.is_interactive, dryrun=dryrun)

    def backup(
        self,
        backup_name,
        *paths,
        exclude_patterns=[],
        timestamp=None,
        snapborg_id=None,
        dryrun=False,
    ):

        borg_create = ["create",
                       "--one-file-system",
                       "--stats",
                       "--exclude-caches",
                       "--checkpoint-interval", "600",
                       "--compression", self.compression]
        if snapborg_id:
            borg_create += ("--comment", f"snapborg_id={snapborg_id}")
        if timestamp:
            borg_create += ("--timestamp", timestamp.isoformat())
        for e in exclude_patterns:
            borg_create += ("--exclude", e)

        if self.is_interactive:
            borg_create.append("--progress")

        repospec = f"{self.repopath}::{backup_name}"
        borg_invocation = borg_create + [repospec, *paths]

        launch_borg(
            borg_invocation,
            self.passphrase,
            log_output=False,
            dryrun=dryrun
        )

    def delete(self, backup_name, dryrun=False):
        borg_delete = ["delete", f"{self.repopath}::{backup_name}"]
        launch_borg(borg_delete, self.passphrase,
                    log_output=self.is_interactive,
                    dryrun=dryrun)

    def prune(self, override_retention_settings=None, dryrun=False):
        override_retention_settings = override_retention_settings or {}
        borg_prune_invocation = ["prune"]
        retention_settings = selective_merge(
            override_retention_settings, self.retention, restrict_keys=True)
        for name, value in retention_settings.items():
            borg_prune_invocation += (f"--{name.replace('_', '-')}",
                                      str(value))

        borg_prune_invocation.append(self.repopath)

        launch_borg(
            borg_prune_invocation,
            self.passphrase,
            log_output=self.is_interactive,
            dryrun=dryrun
        )

    def list_backups(self):
        borg_list = [
            "list",
            "--format",
            "{archive} {id} {name} {start} {time} {comment}",
            "--json",
            f"{self.repopath}",
        ]
        stdout = (
            launch_borg(borg_list, self.passphrase, log_output=False, dryrun=False)
            or "{}"
        )
        data = json.loads(stdout)
        return data.get("archives", [])

    def list_backup_ids(self):
        backup_list = self.list_backups()
        return [backup.get("comment", "=").split("=")[1] for backup in backup_list]

    def get_retention_config(self):
        return self.retention

    @classmethod
    def create_from_config(cls, config):
        if not config["repo"]:
            raise Exception("Target repository not given!")
        borgrepo = config["repo"]
        # inherit default settings
        config = selective_merge(config, DEFAULT_REPO_CONFIG)
        encryption = config["storage"]["encryption"]
        compression = config["storage"]["compression"]
        retention = restrict_keys(
            DEFAULT_REPO_CONFIG["retention"], config["retention"])
        password = None
        if encryption == "none":
            pass
        elif encryption == "repokey":
            password = get_password(config["storage"]["encryption_passphrase"])
        else:
            raise Exception("Invalid or unsupported encryption mode given!")
        return cls(borgrepo, compression, retention=retention, encryption=encryption,
                   passphrase=password)


def get_password(password):
    """
    Try to read the password from a file, if it looks like a filename.
    Taken from the sftbackup project
    """
    if any(password.startswith(char) for char in ('~', '/', '.')):
        try:
            password = os.path.expanduser(password)
            with open(password) as pwfile:
                password = pwfile.read().strip()
        except FileNotFoundError:
            LOG.fatal("tried to use password as file, but could not find it")
            raise

    return password


def launch_borg(args, password=None, log_output=False, dryrun=False):
    """
    launch borg and supply the password by environment

    raises a CalledProcessError when borg doesn't return with 0
    """

    cmd = ["borg"] + args

    LOG.debug("$ {}".format(' '.join(cmd)))
    buffer = ""

    if not dryrun:
        env = {'BORG_PASSPHRASE': password} if password else {}
        # TODO: parse output from JSON log lines

        # launch process
        proc = subprocess.Popen(
            cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        # rather than wait for process to finish, print output in real time
        while proc.poll() is None:
            line = proc.stdout.readline().decode().rstrip("\n")
            if len(line) != 0:
                buffer += line
                if log_output:
                    LOG.info(line)
        if proc.returncode != 0:
            if proc.returncode == 1:
                # warning(s) happened, don't raise
                if log_output:
                    LOG.info(f"Borg command execution gave warnings:\n{buffer}")
            else:
                raise CalledProcessError(cmd=cmd, returncode=proc.returncode)
    return buffer
