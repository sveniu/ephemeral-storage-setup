import logging
import os.path
import sys
import traceback

import yaml

from ephemeral_storage_setup import devices, utils

from .log import CustomJsonFormatter

logger = logging.getLogger()

config_file_paths = [
    "/etc/ephemeral-storage-setup/config.yml",
]


def main():
    # If supplied, treat the first argument as the configuration file.
    if len(sys.argv) > 1:
        config_file_paths.insert(0, sys.argv[1])

    config = None
    for fn in config_file_paths:
        try:
            with open(os.path.expanduser(fn), "r") as f:
                config = yaml.safe_load(f)
                break
        except FileNotFoundError as e:
            logger.debug("config file not found", extra={"path": fn, "exception": e})

    if config is None:
        logger.error(
            "no config file found",
            extra={
                "attempted_paths": config_file_paths,
            },
        )
        raise RuntimeError(
            f"no config file found; tried: {'; '.join(config_file_paths)}"
        )

    # Update log level from config.
    logger.setLevel(config.get("log_level", logging.INFO))

    disks = []
    for dev in devices.scan_devices():
        if not isinstance(dev, devices.Disk):
            logger.info(f"Device {dev.path} not a disk. Skipping.")
            continue

        if dev.is_initialized():
            logger.info(f"Device {dev.path} is already initialized. Skipping.")
            continue

        if not dev.matches_config(config.get("detect", {})):
            logger.info(f"Device {dev.path} doesn't match the detect configuration. Skipping.")
            continue

        disks.append(dev)

    if len(disks) == 0:
        logger.error("no member devices found")
        raise RuntimeError("no member devices found")
    else:
        logger.info(f"Found {len(disks)} member devices: {', '.join([d.path for d in disks])}")

    partitions = []
    for dev in disks:
        new_partition = dev.create_single_partition()
        partitions.append(new_partition)
        logger.info(f"Created partition {new_partition} on disk {dev.path}")

    logging.info(f"Creating mdraid device from {len(partitions)} partitions")

    mdraid = devices.create_mdraid(partitions, config.get("mdraid", {}))
    utils.mkfs(mdraid.path, config.get("mkfs", {}))
    utils.activate_mount(mdraid, config)


def cli():
    logHandler = logging.StreamHandler(sys.stdout)
    formatter = CustomJsonFormatter("%(timestamp)s %(name)s %(level)s %(message)s")
    logHandler.setFormatter(formatter)
    logger.addHandler(logHandler)
    logger.setLevel(logging.NOTSET)

    try:
        main()
    except Exception as e:
        logger.error(
            "unhandled exception; exiting",
            extra={"exception": e, "traceback": traceback.format_exc()},
        )
        sys.exit(1)
