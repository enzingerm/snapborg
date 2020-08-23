import os
import subprocess
import sys

from .util import restrict_keys, selective_merge

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
        borg_init_invocation = ["init", "--encryption",
                                self.encryption, self.repopath]
        launch_borg(borg_init_invocation, self.passphrase,
                    print_output=self.is_interactive, dryrun=dryrun)

    def backup(self, backup_name, *paths, exclude_patterns=[], timestamp=None, dryrun=False):

        borg_create = ["create",
                       "--one-file-system",
                       "--stats",
                       "--exclude-caches",
                       "--checkpoint-interval", "600",
                       "--compression", self.compression]
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
            print_output=self.is_interactive,
            dryrun=dryrun
        )
        # TODO: run prune?

    def delete(self, backup_name, dryrun=False):
        borg_delete = ["delete", f"{self.repopath}::{backup_name}"]
        launch_borg(borg_delete, self.passphrase,
                    print_output=self.is_interactive,
                    dryrun=dryrun)

    def prune(self, override_retention_settings=dict(), dryrun=False):
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
            print_output=self.is_interactive,
            dryrun=dryrun
        )

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
            print("tried to use password as file, but could not find it")
            raise

    return password


def launch_borg(args, password=None, print_output=False, dryrun=False):
    """
    launch borg and supply the password by environment

    raises a CalledProcessError when borg doesn't return with 0
    """

    cmd = ["borg"] + args

    if print_output:
        print(f"$ {' '.join(cmd)}")

    if not dryrun:
        env = {'BORG_PASSPHRASE': password} if password else {}
        # TODO: parse output from JSON log lines
        subprocess.run(cmd,
                       stdout=(None if print_output else subprocess.PIPE),
                       stderr=(None if print_output else subprocess.STDOUT),
                       env=env, check=True)
