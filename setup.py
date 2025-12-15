#!/usr/bin/env python3

from setuptools import find_packages, setup

import snapborg

setup(
    name="snapborg",
    version=snapborg.__version__,
    description="Automated backups of snapper snapshots to borg repositories",
    long_description=(
        "Backup your snapper snapshots with Borg.\nsnapborg is intended"
        "for allowing automated backups of snapshots to external hard drives,"
        "but it can be used to sync snapshots to remote borg repositories as "
        "well.\nBased on sftbackup and inspired by borgmatic, snapborg is just "
        "a wrapper for Borg. You can use Borg commands directly if you prefer."
    ),
    maintainer="Marinus Enzinger",
    maintainer_email="marinus@enzingerm.de",
    url="https://github.com/enzingerm/snapborg",
    license="GPL3+",
    python_requires=">=3.7, <4",
    install_requires=[
        "pyyaml",
        "packaging",
        "dacite"
    ],
    packages=find_packages(exclude=["tests*"]),
    entry_points={
        "console_scripts": [
            "snapborg = snapborg.commands:main",
        ],
    },
    data_files=[
        (
            "/etc/",
            [
                "etc/snapborg.yaml",
            ],
        ),
        (
            "/usr/lib/systemd/system/",
            [
                "usr/lib/systemd/system/snapborg-backup-all.service",
                "usr/lib/systemd/system/snapborg-backup-all-daily.timer",
                "usr/lib/systemd/system/snapborg-backup-all-hourly.timer",
                "usr/lib/systemd/system/snapborg-backup@.service",
                "usr/lib/systemd/system/snapborg-backup-daily@.timer",
                "usr/lib/systemd/system/snapborg-backup-hourly@.timer",
            ],
        ),
    ],
    platforms=[
        "Linux",
    ],
    classifiers=[
        (
            "License :: OSI Approved :: "
            "GNU General Public License v3 or later (GPLv3+)"
        ),
        "Environment :: Console",
        "Operating System :: POSIX :: Linux",
        "Intended Audience :: System Administrators",
        "Programming Language :: Python",
        "Topic :: System :: Archiving :: Backup",
    ],
)
