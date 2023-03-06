# snapborg

Automated backups of [snapper](https://github.com/openSUSE/snapper) snapshots to [borg](https://github.com/borgbackup/borg) repositories. Based on [sftbackup](https://github.com/SFTtech/sftbackup) and inspired by [borgmatic](https://torsion.org/borgmatic/).

## How it works
Snapper operates on one or many configs for filesystems or subvolumes, for each of which automated snapshots are created. Often only a single config called `root` is used. The `snapborg` configuration file (`/etc/snapborg.yaml`) is used to create a mapping `(snapper config) <-> (borg repository)` and then those snapshots created by `snapper` are transferred to the remote (or local) borg repository.

A very basic snapborg configuration would look like this:
```yaml
configs:
  - name: root
    repo: backupuser@backuphost:root
```

Normally you might not want to synchronize all the snapper snapshots to the remote backup destination, thus per-repo retention settings can be configured to determine which snapshots will actually be backed up. Note that by default, old snapshots will be pruned from the borg archive according to the retention settings, unless the `--no-prune` flag is given.

*Example*:

Snapper creates hourly snapshots, but you only want to transfer the most recent snapshot, one snapshot for each of the past 6 months and one snapshot for each of the past 3 years. The config would look as follows:
```yaml
configs:
  - name: snapper_config_1
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


### Fault tolerant mode
In some scenarios, the backup target repository is not permanently reachable, e. g. when an 
external HDD is used which is only plugged in from time to time. In these cases, normally
an execution of `snapborg` would fail. However `snapborg` features a fault tolerant mode, which
can be enabled by specifying the following in `snapborg.cfg`:
```yaml
configs:
  - name: snapper_config_1
    ...
    fault_tolerant_mode: true
    last_successful_backup_max_age: <time period>
    ...
```
`<time period>` must be given as days (e.g. `"3d"`) or as hours (e.g. `"6h"`) and specifies the maximum age of the last backup successfully transferred to the borg repo. When `snapborg` cannot transfer a recent snapshot to the repository, it will only fail if the last snapshot which was transferred during an earlier executions older than the given time period.

## Usage
```
# snapborg [general options] <command> [command options]

General options:
  --cfg             Snapborg config file (defaults to /etc/snapborg.yaml)
  --dryrun          Don't actually do anything
  --snapper-config  Only operate on a single snapper config
                    given by its name
  -v                increase verbosity, can be repeated twice

Commands:
  init          Initialize (create) the configured borg repositories

  list          List all snapper snapshots and show whether
                they are already backed up

  prune         Prune old borg backup archives

  backup        Backup snapper snapshots
    --recreate  Delete possibly existing borg archives and recreate them from
                scratch
    --no-prune  Ignore retention policy and don't prune old backups

  clean-snapper Delete snapborg metadata stored alongside
                snapper snapshots


```

## Dependencies
- snapper >= 0.8.6
- borg
- *Python*:
  - packaging
  - pyyaml