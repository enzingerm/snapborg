import os
import os.path
import subprocess
import sys
from contextlib import contextmanager
from subprocess import CalledProcessError

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
    def __init__(self, snapper_config: str, repopath: str, compression: str, retention, encryption="none",
                 passphrase=None):
        self.repopath = repopath
        self.compression = compression
        self.retention = retention
        self.encryption = encryption
        self.passphrase = passphrase
        self.snapper_config = snapper_config
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
                    print_output=self.is_interactive, dryrun=dryrun)

    def backup(self, backup_name, path, exclude_patterns=[], timestamp=None, dryrun=False, mount_path=None):

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
        args = borg_create + [repospec, '.']

        if mount_path is not None:
            with bind_mount(mount_path, path):
                launch_borg(
                    args,
                    self.passphrase,
                    print_output=self.is_interactive,
                    dryrun=dryrun,
                    cwd=mount_path,
                )
        else:
            launch_borg(
                args,
                self.passphrase,
                print_output=self.is_interactive,
                dryrun=dryrun,
                cwd=path,
            )

    def delete(self, backup_name, dryrun=False):
        borg_delete = ["delete", f"{self.repopath}::{backup_name}"]
        launch_borg(borg_delete, self.passphrase,
                    print_output=self.is_interactive,
                    dryrun=dryrun)

    def prune(self, override_retention_settings=None, dryrun=False):
        override_retention_settings = override_retention_settings or {}
        borg_prune_invocation = ["prune", "--list"]
        retention_settings = selective_merge(
            override_retention_settings, self.retention, restrict_keys=True)
        for name, value in retention_settings.items():
            borg_prune_invocation += (f"--{name.replace('_', '-')}",
                                      str(value))

        borg_prune_invocation += ("--glob-archives", f"'{self.snapper_config}-*'")
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
        if not config["name"]:
            raise Exception("Snapper config name not given!")
        borgrepo = config["repo"]
        snapper_config = config["name"]
        # inherit default settings
        config = selective_merge(config, DEFAULT_REPO_CONFIG)
        encryption = config["storage"]["encryption"]
        compression = config["storage"]["compression"]
        retention = restrict_keys(
            DEFAULT_REPO_CONFIG["retention"], config["retention"])
        password = None
        if encryption == "none":
            pass
        elif encryption == "repokey" or encryption == "repokey-blake2":
            password = get_password(config["storage"]["encryption_passphrase"])
        else:
            raise Exception("Invalid or unsupported encryption mode given!")
        return cls(snapper_config, borgrepo, compression, retention=retention, encryption=encryption,
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


def launch_borg(args, password=None, print_output=False, dryrun=False, cwd=None):
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
        try:
            if print_output:
                subprocess.run(cmd, env=env, check=True, cwd=cwd)
            else:
                subprocess.check_output(cmd,
                                        stderr=subprocess.STDOUT,
                                        env=env,
                                        cwd=cwd)
        except CalledProcessError as e:
            if e.returncode == 1:
                # warning(s) happened, don't raise
                if not print_output:
                    print(f"Borg command execution gave warnings:\n{e.output.decode()}")
            else:
                raise


@contextmanager
def bind_mount(mount_path, target_path):
    """
    Creates a bind mount mounted at mount_path pointing to target_path.  Usually requires root privileges.
    """

    try:
        os.makedirs(mount_path, exist_ok=True)
    except PermissionError as exc:
        raise Exception("Failed to create bind mount dir; most likely you should re-run this command as root") from exc

    # If we didn't properly clean this up in previous invocations
    while os.path.ismount(mount_path):
        subprocess.check_call(['umount', mount_path])

    subprocess.check_call(['mount', '--bind', target_path, mount_path])
    try:
        yield
    finally:
        subprocess.check_call(['umount', mount_path])
