#!/usr/bin/python3

import json
import logging
import os
import stat

from ephemeral_storage_setup import execute, utils

logger = logging.getLogger()


class BlockDevice:
    class Unknown(Exception):
        pass

    _registry = {}  # Registered subclasses.

    def __init_subclass__(cls) -> None:
        """Register subclasses for later instantiation."""
        super().__init_subclass__()
        cls._registry[cls.device_type_prefix] = cls  # Add class to registry.

    def __new__(cls, device_info):
        """Create instance of appropriate subclass."""
        subclass = None
        for prefix in cls._registry:
            if device_info["type"].startswith(prefix):
                subclass = cls._registry[prefix]
                break
        if subclass:
            return object.__new__(subclass)
        else:
            # No subclass with matching type found (and no default).
            raise cls.Unknown(f"""device type "{device_info["type"]}" not found""")

    def __init__(self, raw_info):
        self.raw_info = raw_info

    def configure(self, config):
        self.config = config

    @property
    def path(self):
        return self.raw_info["path"]

    @property
    def uuid(self):
        return self.raw_info["uuid"].lower()

    @property
    def children(self):
        for child in self.raw_info["children"]:
            yield BlockDevice(child)

    def rescan(self):
        self.raw_info = scan_devices(self.path)[0]

    def matches_config(self, config) -> bool:
        # Check device model.
        if not self.raw_info["model"] in config.get(
            "models",
            (
                "Amazon EC2 NVMe Instance Storage",
                "Amazon Elastic Block Store",
            ),
        ):
            return False

        # Check device size.
        if self.raw_info["size"] / 1024**3 < config.get("min_size_gb", 2):
            return False

        max_size_gb = config.get("max_size_gb", None)
        if max_size_gb is not None:
            if self.raw_info["size"] / 1024**3 > max_size_gb:
                return False

        return True


class Disk(BlockDevice):
    device_type_prefix = "disk"

    def __init__(self, raw_info):
        super().__init__(raw_info)

    def is_initialized(self) -> bool:
        # Check for existing partition table.
        if not self.raw_info["pttype"] is None:
            return True

        # Check for existing children (partitions, md, crypto, etc).
        children_raw = self.raw_info.get("children", [])
        if len(children_raw) > 0:
            return True

        # Check for existing filesystem.
        if not self.raw_info["fstype"] is None:
            return True

        # Check for existing filesystem.
        if not self.raw_info["fssize"] is None:
            return True

        return False

    @utils.udev_settle
    def create_single_partition(self):
        execute.simple(
            [
                "parted",
                "--script",
                "--align",
                "optimal",
                "--",
                self.path,
                " ".join(
                    (
                        "mklabel gpt",
                        "mkpart ephemeral ext2 4MiB 100%",
                        "set 1 raid on",
                    ),
                ),
            ]
        )

        # Re-read device info after partitioning.
        self.rescan()


class Partition(BlockDevice):
    device_type_prefix = "part"

    def __init__(self, info):
        super().__init__(info)


class MDRaid(BlockDevice):
    device_type_prefix = "raid"

    def __init__(self, info):
        super().__init__(info)


@utils.udev_settle
def scan_devices(device_path=None):
    argv = [
        "lsblk",
        "--json",
        "--bytes",
        "--output-all",
    ]
    if device_path is not None:
        argv.append(device_path)

    stdout, _ = execute.simple(argv)
    raw_devices = json.loads(stdout)["blockdevices"]

    devices = []
    for raw_info in raw_devices:
        try:
            block_device = BlockDevice(raw_info)
        except BlockDevice.Unknown:
            continue

        devices.append(block_device)

    return devices


@utils.udev_settle
def create_mdraid(member_devices, config):
    argv = [
        "mdadm",
        "--create",
        config.get("name", "ephemeral"),
        f'--level={config.get("raid_level", "0")}',
    ]

    member_count = len(member_devices)
    if member_count == 1 and config.get("allow_single_member", True):
        argv.append("--force")

    argv.append(f"--raid-devices={member_count}")

    for member in member_devices:
        argv.append(member.path)

    execute.simple(argv)

    device_path = f'/dev/md/{config.get("name", "ephemeral")}'
    if not stat.S_ISBLK(os.stat(device_path).st_mode):
        raise RuntimeError(f"not a block device: {device_path}")

    return scan_devices(device_path)[0]
