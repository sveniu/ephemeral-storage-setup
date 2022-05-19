"""
Classes and methods for interacting with block devices, based on data obtained
from lsblk/udev.
"""

import json
import logging
import os
import stat
import uuid

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
        self.rescan()
        return self.raw_info["uuid"].lower()

    @property
    def partuuid(self):
        self.rescan()
        return self.raw_info["partuuid"].lower()

    @property
    def children(self):
        self.rescan()
        for child in self.raw_info["children"]:
            yield BlockDevice(child)

    @property
    def sector_size(self):
        return self.raw_info["phy-sec"]

    def rescan(self):
        self.raw_info = scan_devices_raw(self.path)[0]

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
        if "min_size" in config:
            min_size = utils.to_bytes(config["min_size"])
            if min_size >= 0 and self.raw_info["size"] < min_size:
                return False

        if "max_size" in config:
            max_size = utils.to_bytes(config["max_size"])
            if max_size > 0 and self.raw_info["size"] > max_size:
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

        # Check for existing label.
        if not self.raw_info["label"] is None:
            return True

        # Check for existing uuid.
        if not self.raw_info["uuid"] is None:
            return True

        return False

    @utils.udev_settle
    def create_single_partition(self):
        """
        Create a single GPT partition using sgdisk. Align the start of the
        partition at 4 MiB for the least likelihood of performance issues. Use
        the "Linux RAID" partition type to ensure auto assembly on boot.
        """

        # Calculate the starting sector corresponding to 4 MiB, as sgdisk only
        # accepts sector numbers for alignment.
        sector_start = 4 * 1024**2 // self.sector_size

        # Set the partition type to "Linux RAID" (aka 0xfd00), which enables
        # auto assembly on boot.
        partition_type = "a19d880f-05fc-4d3b-a006-743f0f84911e"

        # Get a unique partition GUID for a robust way of returning the
        # partition to the caller.
        partition_guid = str(uuid.uuid4())

        utils.create_single_partition(
            self.path,
            sector_start=sector_start,
            partition_type=partition_type,
            partition_guid=partition_guid,
        )

        for child in self.children:
            if child.partuuid == partition_guid:
                return child

        return None


class Partition(BlockDevice):
    device_type_prefix = "part"

    def __init__(self, raw_info):
        super().__init__(raw_info)


class MDRaid(BlockDevice):
    device_type_prefix = "raid"

    def __init__(self, raw_info):
        super().__init__(raw_info)


def scan_devices_raw(device_path=None):
    """
    Run lsblk and return its raw data.
    """

    argv = [
        "lsblk",
        "--json",
        "--bytes",
        "--output-all",
    ]
    if device_path is not None:
        argv.append(device_path)

    stdout, _ = execute.simple(argv)
    return json.loads(stdout)["blockdevices"]


def scan_devices(device_path=None):
    """
    Scan for block devices and return a list of BlockDevice objects.
    """

    devices = []
    for raw_info in scan_devices_raw(device_path):
        try:
            block_device = BlockDevice(raw_info)
        except BlockDevice.Unknown:
            continue

        devices.append(block_device)

    return devices


@utils.udev_settle
def create_mdraid(member_devices, config):
    """
    Create an MD RAID device using the supplied config.
    """

    md_name = config.get("name", "ephemeral")
    argv = [
        "mdadm",
        "--create",
        md_name,
        "--homehost=any",
        f"""--level={str(config.get("level", 0))}""",
    ]

    member_count = len(member_devices)
    if member_count == 1:
        argv.append("--force")

    argv.append(f"--raid-devices={member_count}")

    for member in member_devices:
        argv.append(member.path)

    execute.simple(argv)

    device_path = f"/dev/md/{md_name}"
    if not stat.S_ISBLK(os.stat(device_path).st_mode):
        raise RuntimeError(f"not a block device: {device_path}")

    return scan_devices(device_path)[0]
