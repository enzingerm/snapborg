from dataclasses import asdict
import os
import subprocess
import sys
from contextlib import contextmanager
from subprocess import CalledProcessError
from typing import List, Optional

from .config import RepoConfig, RetentionConfig, SnapborgSnapperConfig
from .exceptions import BindMountError, BorgExecutionException, PermissionError as SnapborgPermissionError

BORG_RETURNCODE_ARCHIVE_EXISTS = 30

class BorgRepo:
    def __init__(self, snapper_config: SnapborgSnapperConfig, repo_config: RepoConfig, dryrun: bool = False):
        self.snapper_config = snapper_config
        self.repo_config = repo_config
        self.dryrun = dryrun
        self.is_interactive = os.isatty(sys.stdout.fileno())

    def backup(self, backup_name, path, timestamp=None, mount_path=None):

        borg_create_args = []
        if not self.dryrun:
            # --dry-run and --stats are mutually exclusive
            borg_create_args += ("--stats",)
        if timestamp:
            borg_create_args += ("--timestamp", timestamp.isoformat())

        # add given parameters from repo config
        for param, value in self.repo_config.create_params.items():
            param = "--" + param.replace("_", "-")
            if isinstance(value, list):
                for v in value:
                    borg_create_args += (param, str(v))
            elif value == True:
                borg_create_args += (param,)
            elif value != False:
                borg_create_args += (param, str(value))

        if self.is_interactive:
            borg_create_args.append("--progress")

        repospec = f"{self.repo_path}::{backup_name}"
        args = borg_create_args + [repospec]

        if mount_path is not None:
            with bind_mount(mount_path, path):
                self.launch_borg("create", args + [mount_path])
        else:
            self.launch_borg("create", args + ['.'], cwd=path)

    def delete(self, backup_name: str):
        self.launch_borg("delete", [f"{self.repo_path}::{backup_name}"])

    def prune(self):
        borg_prune_args = ["--list"]
        for name, value in asdict(self.retention_config).items():
            borg_prune_args += (f"--{name.replace('_', '-')}", str(value))

        borg_prune_args += ("--glob-archives", f"{self.snapper_config.name}-*")
        borg_prune_args.append(self.repo_path)
        
        self.launch_borg("prune", borg_prune_args)

    @property
    def repo_path(self) -> str:
        return self.repo_config.path

    @property
    def retention_config(self) -> RetentionConfig:
        return self.repo_config.retention

    @property
    def name(self) -> str:
        return self.repo_config.name

    @classmethod
    def create_from_config(cls, snapper_config: SnapborgSnapperConfig, repo_config: RepoConfig, dryrun=False):
        return cls(snapper_config, repo_config, dryrun)
    
    def launch_borg(self, cmd: str, args: List[str], cwd: Optional[str] = None, common_args: List[str] = []):
        if self.dryrun:
            # this assumes that every borg command issued supports the --dry-run flag
            args.insert(0, "--dry-run")
        return launch_borg(common_args + [cmd] + args, print_output=self.is_interactive,
                           cwd=cwd, env=self.repo_config.environment)


def launch_borg(args, print_output=False, cwd=None, env: dict = {}):
    """
    launch borg and supply the password by environment

    raises a CalledProcessError when borg returns with 2
    """

    cmd = ["borg"] + args

    if print_output:
        print(f"$ {' '.join(cmd)}")

    # Start with a copy of the current environment
    env = os.environ.copy()

    for key, value in env.items():
        env[key] = value
    
    env['BORG_EXIT_CODES'] = 'modern'

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
        if e.returncode == 1 or 100 <= e.returncode <= 127:
            # warning(s) happened, don't raise
            if not print_output:
                print(f"Borg command execution gave warnings:\n{e.output.decode()}")
        else:
            raise BorgExecutionException(e.returncode)


@contextmanager
def bind_mount(mount_path, target_path):
    """
    Creates a bind mount mounted at mount_path pointing to target_path.  Usually requires root privileges.
    """

    try:
        os.makedirs(mount_path, exist_ok=True)
    except PermissionError as exc:
        raise SnapborgPermissionError("Failed to create bind mount dir; most likely "
                                      "you should re-run this command as root") from exc

    # If we didn't properly clean this up in previous invocations
    try:
        while os.path.ismount(mount_path):
            subprocess.check_call(['umount', mount_path])

        subprocess.check_call(['mount', '--bind', target_path, mount_path])
        try:
            yield
        finally:
            subprocess.check_call(['umount', mount_path])
    except subprocess.CalledProcessError as e:
        raise BindMountError from e

