# snapborg

Automated backups of [snapper](https://github.com/openSUSE/snapper) snapshots to [borg](https://github.com/borgbackup/borg) repositories. Based on [sftbackup](https://github.com/SFTtech/sftbackup) and inspired by [borgmatic](https://torsion.org/borgmatic/).

## USE WITH CAUTION - Snapborg 0.2 is still alpha and might corrupt/lose your data

## How it works
Snapper operates on one or many configs for filesystems or subvolumes, for each of which automated snapshots are created. Often only a single config called `root` is used. The `snapborg` configuration file (`/etc/snapborg.yaml`) is used to create a one-to-many mapping `(snapper config) --> (borg repositories)` and then those snapshots created by `snapper` are transferred to the remote (or local) borg repositories. Bookkeeping is simply done by the means of snapper userdata key/value pairs.

A very basic snapborg configuration would look like this:
```yaml
configs:
  - name: root
    repos:
      - name: root_repo
        path: backupuser@backuphost:root
```

### Retention settings

Normally you might not want to synchronize all the snapper snapshots to the remote backup destination, thus per-repo retention settings can be configured to determine which snapshots will actually be backed up. Note that by default, old snapshots will be pruned from the borg archive according to the retention settings, unless the `--no-prune` flag is given.

*Example*:

Snapper creates hourly snapshots, but you only want to transfer the most recent snapshot, one snapshot for each of the past 6 months and one snapshot for each of the past 3 years. The config would look as follows:
```yaml
configs:
  - name: snapper_config_1
    repos:
      - name: main_repo
        ...
        retention:
          keep_last: 1
          keep_hourly: 0
          keep_daily: 0
          keep_weekly: 0
          keep_monthly: 6
          keep_yearly: 3
        ...
```

### Parameters for borg

Parameters supplied to `borg create` for the backup can be specified as follows. The
parameters should be given in their long form and a underscore _ should be used instead
of the dash -
```yaml
configs:
  - name: snapper_config_1
    repos:
      - name: main_repo
        ...
        create_params:
          numeric_owner: true # parameters without arguments are given as boolean values,
                              # use false to disable a parameter which would be set per default
          exclude: ["sh:home/*/.thumbnails", "*.pyc"] # if a parameter should be given multiple
                                                      # times, a list can be given
          exclude_if_present: .cachedir # a normal parameter with one argument
        ...
```

### Fault tolerant mode
In some scenarios, the backup target repository is not permanently reachable, e. g. when an 
external HDD is used which is only plugged in from time to time. In these cases, normally
an execution of `snapborg` would fail. However `snapborg` features a fault tolerant mode, which
can be enabled by specifying the following in `snapborg.yaml`:
```yaml
configs:
  - name: snapper_config_1
    repos:
      - name: main_repo
        ...
        fail_after: true # this repo is mandatory
        ...
      - name: secondary_repo
        ...
        fail_after: 30d # this repo fails when the most recent transferred snapshot is
                        # older than 30 days
        ...
      - name: external_hdd
        ...
        fail_after: false # this repo is completely optional
        ...
```
If a time period is defined for `fail_after`, it must be given as days (e.g. `"3d"`) or as hours (e.g. `"6h"`) and specifies the maximum age of the last backup successfully transferred to the borg repo. When `snapborg` cannot transfer a recent snapshot to the repository, it will only fail if the most recent snapshot which was transferred during an earlier execution is older than the given time period.

## Usage

### Command line
```
# snapborg [general options] <command> [command options]

General options:
  --cfg               Snapborg config file (defaults to /etc/snapborg.yaml)
  --dryrun            Don't actually do anything
  --bind-mount        OBSOLETE/has no effect: see --absolute-paths parameter of the `backup` command
  --snapper-config    Only operate on a single snapper config
                      given by its name

Commands:
  list                List all snapper snapshots and show whether
                      they are already backed up

  prune               Prune old borg backup archives

  backup              Backup snapper snapshots
    --absolute-paths  Archive files in the btrfs subvolume with their absolute paths. Requires
                      running as root (uses bind-mount).If not given, files are stored with their
                      paths relative to the subvolume root.
    --recreate        Delete possibly existing borg archives and recreate them from
                      scratch
    --no-prune        Ignore retention policy and don't prune old backups

  clean-snapper       Delete snapborg metadata stored alongside
                      snapper snapshots


```

### Systemd units

You will find relevant systemd units in `usr/lib/systemd/system/`.

  * To enable regular backups for all configs, run `systemctl enable --now snapborg-backup-all-hourly.timer`
  * To enable regular backups for a specific config, run `systemctl enable --now snapborg-backup-hourly@configname.timer` for each config (replace `configname` with your config's name)
  * You can also run backups daily; just use `daily` instead of `hourly` above.
  * To customize the default configuration, don't modify the packaged systemd unit files directly; instead, make a copy
    or a drop-in of the unit file under `/etc/systemd/system`.  This can easily be done with `systemctl edit [--full] <unit file>`.

## Dependencies
- snapper >= 0.8.6
- borg
- *Python*:
  - packaging
  - pyyaml
  - dacite


# Changelog


## 0.2-alpha
- A new configuration file format has been introduced which allows for multiple borg repos
  for a single snapper config
  - every borg repo now gets a unique name so that the path can be changed in the future
    without affecting the snapborg/snapper metadata
  - retention settings can be different for each borg repo
  - a borg repo can be completely optional (so that snapborg doesn't fail when the repo is
    unreachable)
  - also a time limit can be configured which specifies the maximum age of the last successfully
    transferred snapshot to the repo, if the time limit is exceeded, the snapborg call fails
    This is equivalent to the previous `fault_tolerant_mode` in combination with `last_backup_max_age`
  - per default, a borg repo is mandatory, so snapborg fails if any error occurs during backup
    or the repo is unaccessible
  - there is a compatibility layer in the code which ensures backwards compatibility to the old
    configuration file format
  - when the user switches to the new configuration file format, and assigns a unique name to the
    borg repo, the metadata in the snapper snapshots will automatically be updated to reference
    the new (named) repo config. This way, the existing archives won't have to be recreated.

- Ability to provide arbitrary parameters to `borg create` via `create_params` config section
- Ability to provide arbitrary environment variables to borg via `environment` config section
- Streamlined the configuration and put some directives to a more logical place
  - `exclude_patterns` is now just a normal entry under `create_params`
  - for `compression`, the same applies
  - `borg_passphrase` is now just a normal entry under `environment`

#### Removed Features:
- `snapborg init` command
- provide a file name as borg passphrase so that the file contents is used as the actual passphrase
  

## 0.1.1
  - Remove `--bind-mount` parameter which was needed to strip the snapper snapshot prefix 
    (`<subvol>/.snapshots/<number>/snapshot`) from the archive path. This is now the default
    behaviour and uses the borg "slashdot hack" to specify a recursion root which doesnt need
    special privileges.
  - Introduce `snapborg backup --absolute-paths` parameter which can be used so that files in
    snapper configs mounted somewhere down the filesystem tree can be backed up with their full
    absolute paths. `/home/user/testdir/testfile` keeps its absolute path in the archive even if 
    subvolume `@home` is mounted at `/home/user`. Per default it would be stored as `testdir/testfile`
    (relative to the subvolume root). **Uses bind mounts and requires special privileges**