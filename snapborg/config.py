from dataclasses import dataclass, field
from datetime import timedelta
from typing import List, Dict, Optional, Union
import sys
import yaml
import os
import re

from dacite import from_dict, Config, UnexpectedDataError, MissingValueError, WrongTypeError, StrictUnionMatchError

from .util import selective_merge
from .exceptions import ConfigError

LEGACY_REPO_NAME = "__main_repo"


@dataclass
class RetentionConfig:
    keep_last: int = 1
    keep_hourly: int = 0
    keep_daily: int = 7
    keep_weekly: int = 4
    keep_monthly: int = 3
    keep_yearly: int = 5

@dataclass
class OldStorageConfig:
    """Kept to be backwards compatible to old snapborg configs"""
    encryption: str = "none"
    encryption_passphrase: Optional[str] = None
    compression: str = "auto,zstd,4"

@dataclass
class OldSnapperConfig:
    """Kept to be backwards compatible to old snapborg configs"""
    name: str
    repo: str
    fault_tolerant_mode: bool = False
    last_backup_max_age: str = "0d"
    exclude_patterns: List[str] = field(default_factory=list)
    retention: RetentionConfig = field(default_factory=RetentionConfig)
    storage: OldStorageConfig = field(default_factory=OldStorageConfig)

@dataclass
class OldSnapborgConfig:
    """Kept to be backwards compatible to old snapborg configs"""
    configs: List[OldSnapperConfig]

    def as_new_config(self):
        return SnapborgConfig([
            SnapborgSnapperConfig(sc.name, [
                RepoConfig(
                    LEGACY_REPO_NAME,
                    sc.repo,
                    sc.last_backup_max_age if sc.fault_tolerant_mode else True,
                    {
                        "exclude": [str(v) for v in sc.exclude_patterns],
                        "compression": sc.storage.compression
                    },
                    {"BORG_PASSPHRASE": sc.storage.encryption_passphrase} if sc.storage.encryption_passphrase else {},
                    sc.retention,
                    _created_from_legacy_config=True
                )
            ])
            for sc in self.configs
        ])


@dataclass
class RepoConfig:
    name: str
    path: str
    fail_after: Union[bool, str] = True
    create_params: Dict[str, Union[bool, int, str, List[Union[str, int]]]] = field(default_factory=dict) 
    environment: Dict[str, Union[str, int]] = field(default_factory=dict)
    retention: RetentionConfig = field(default_factory=RetentionConfig)
    # field for internal use
    _fail_after: Optional[timedelta] = None
    _created_from_legacy_config: bool = False

    def __post_init__(self):
        if not self.name.isidentifier() or not self.name.islower():
            raise ConfigError(f"Invalid repo name '{self.name}': Only a-z0-9_ are allowed"
                                " characters for the borg repo name!")
        if self.name == LEGACY_REPO_NAME and not self._created_from_legacy_config:
            raise ConfigError(f"A repo in the 0.2+ config file format cannot be named {LEGACY_REPO_NAME}!")
        if isinstance(self.fail_after, str):
            res = re.fullmatch("(\\d+)(d|h)", self.fail_after)
            if not res:
                raise ConfigError("'fail_after' must be given as a number followed by 'h' for hours or 'd' for days e.g. 12h or 30d")
            val = int(res.group(1))
            self._fail_after = timedelta(hours=val if res.group(2) == "h" else val * 24)
        
        self.environment = { key.upper(): value for key, value in self.environment.items() }
        
        self.create_params = selective_merge(self.create_params, {
            'one_file_system': True,
            'exclude_caches': True,
            'checkpoint_interval': 600,
            'compression': 'auto,zstd,4'
        })

    def get_fail_after(self) -> Union[bool, timedelta]:
        return bool(self.fail_after) if self._fail_after is None else self._fail_after
    
    @property
    def is_old_config(self):
        return self.name == LEGACY_REPO_NAME



@dataclass
class SnapborgSnapperConfig:
    name: str
    repos: List[RepoConfig]


@dataclass
class SnapborgConfig:
    configs: List[SnapborgSnapperConfig]

    def as_new_config(self):
        return self

def load_config(file: str) -> SnapborgConfig:
    """Load the snapborg config from a file and validate it"""
    try:
        with open(file, 'r') as stream:
            cfg = yaml.safe_load(stream)
    except Exception as e:
        raise ConfigError from e

    try:
        config = from_dict(OldSnapborgConfig, cfg, config=Config(strict=True))
        print("WARNING: please switch to new snapborg config file format!", file=sys.stderr)
    except:
        try:
            config = from_dict(SnapborgConfig, cfg, config=Config(strict=True))
        except UnexpectedDataError as e:
            formatted_keys = ", ".join(f'"{key}"' for key in e.keys)
            raise ConfigError(f"Unexpected config parameters: {formatted_keys}")
        except MissingValueError as e:
            raise ConfigError(f"Missing config value: {e.field_path}")
        except WrongTypeError as e:
            raise ConfigError from e
        except StrictUnionMatchError as e:
            raise ConfigError from e

    config = config.as_new_config()

    # duplicate configs are not allowed
    if len(set(c.name for c in config.configs)) != len(config.configs):
        raise ConfigError("Duplicate config sections found!")

    # the feature to load a repo passphrase from a file is not supported anymore
    passphrases = [value \
                    for snapper_config in config.configs
                    for repo in snapper_config.repos
                    for key, value in repo.environment.items()
                    if key == "BORG_PASSPHRASE"]
    if any(os.path.isfile(passphrase) for passphrase in passphrases):
        raise ConfigError("Filenames are not allowed as repository passphrases anymore. Please specify "
                            "the passphrase literally or via BORG_PASSPHRASE environment variable!")
    
    return config

