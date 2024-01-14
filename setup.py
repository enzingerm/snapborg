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
        "but it can be used to sync snapshots to a local borg repository as "
        "well.\nBased on sftbackup and inspired by borgmatic, snapborg is just "
        "a wrapper for Borg. You can use Borg commands directly if you prefer."
    ),
    maintainer="Marinus Enzinger",
    maintainer_email="marinus@enzingerm.de",
    url="https://github.com/enzingerm/snapborg",
    license="GPL3+",
    install_requires=[
        "pyyaml",
        "packaging",
    ],
    packages=find_packages(exclude=["tests*"]),
    entry_points={
        "console_scripts": [
            "snapborg = snapborg.commands.snapborg:main",
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
            "/etc/systemd/system/",
            [
                "etc/systemd/system/snapborg-backup-all.service",
                "etc/systemd/system/snapborg-backup-all.timer",
                "etc/systemd/system/snapborg-backup@.service",
                "etc/systemd/system/snapborg-backup@.timer",
                "etc/systemd/system/snapborg-prune.service",
                "etc/systemd/system/snapborg-prune.timer",
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
