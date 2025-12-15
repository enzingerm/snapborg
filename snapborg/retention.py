from datetime import datetime, time, timedelta

from typing import List

from .util import split
from .snapper import SnapperSnapshot


def get_retained_snapshots(snapshots, date_key, keep_last=1, keep_minutely=0, keep_hourly=0,
                           keep_daily=0, keep_weekly=0, keep_monthly=0, keep_yearly=0) -> List[SnapperSnapshot]:
    """
    Given a list of snapshots and retainment settings, return a sublist consisting
    of those snapshots which should be retained.
    """
    now = datetime.now()
    today = now.date()
    start_of_today = datetime.combine(today, time.min)
    retained = set()
    with_date = sorted([(date_key(snapshot), snapshot)
                        for snapshot in snapshots], key=lambda entry: entry[0])
    if keep_last > 0:
        retained.update(it[1] for it in with_date[-keep_last:])
    # Transform each retainment setting (minutely, hourly, ...) into a tuple of the following form:
    # (<snapshots to keep>,
    #  <lambda to calculate (given interval start time) -> (start time of the preceding interval)>
    #  <datetime of the most recent interval>)
    timedeltas = [
        (keep_minutely, lambda x: x - timedelta(minutes=1),
         datetime.combine(today, time(now.hour, now.minute))),
        (keep_hourly, lambda x: x - timedelta(hours=1), datetime.combine(today, time(now.hour))),
        (keep_daily, lambda x: x - timedelta(days=1), start_of_today),
        (keep_weekly, lambda x: x - timedelta(weeks=1),
         start_of_today - timedelta(days=today.weekday())),
        (keep_monthly, lambda x: datetime(x.year if x.month != 1 else x.year - 1,
                                          (x.month + 10) % 12 + 1,  # one month earlier
                                          1), datetime(today.year, today.month, 1)),
        (keep_yearly, lambda x: datetime(x.year - 1, 1, 1), datetime(today.year, 1, 1))
    ]
    # now iterate over all the retainment settings, calculate the corresponding snapshots to be
    # retained and add those to the result set
    for nr_keep, prev_date_fn, first_date in timedeltas:
        interval = (first_date, now)
        snapshots_remaining = with_date
        while nr_keep > 0 and len(snapshots_remaining) > 0:
            start, end = interval
            snapshots_to_consider, snapshots_remaining = split(
                snapshots_remaining, lambda x: x[0] >= start and x[0] < end)
            # when pruning, borg keeps the last snapshot of an interval. By selecting the last
            # snapshot here, we ensure we aren't backing up snapshots just to prune them right away
            # https://borgbackup.readthedocs.io/en/stable/usage/prune.html#description
            last_snapshot = max(
                snapshots_to_consider,
                key=lambda x: x[0],
                default=None
            )
            if last_snapshot is not None:
                retained.add(last_snapshot[1])
                nr_keep -= 1
            interval = (prev_date_fn(interval[0]), interval[0])
    return list(retained)
