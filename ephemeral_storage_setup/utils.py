import io
import os
import os.path
import shutil
import tarfile

from ephemeral_storage_setup import execute


DEFAULT_FSTYPE = "ext4"


def udev_settle(func):
    """
    Run `udevadm settle` before and after the function is called.
    """

    def wrapper(*args, **kwargs):
        execute.simple(["udevadm", "settle"])
        retval = func(*args, **kwargs)
        execute.simple(["udevadm", "settle"])
        return retval

    return wrapper


@udev_settle
def create_single_partition(
    dev_path,
    sector_start,
    partition_type,
    partition_guid,
):
    execute.simple(
        [
            "sgdisk",
            f"--set-alignment={sector_start}",
            "--largest-new=1",
            f"--typecode=1:{partition_type}",
            f"--partition-guid=1:{partition_guid}",
            dev_path,
        ]
    )


@udev_settle
def mkfs(device_path, config):
    """
    Create a filesystem on the given device, based on the supplied config.
    """

    argv = config.get(
        "command",
        [
            f"mkfs.{DEFAULT_FSTYPE}",
            "-L",
            config.get("label", "ephemeral"),
            "-m",
            str(config.get("reserved_blocks_percentage", 0)),
        ],
    )
    argv.append(device_path)
    execute.simple(argv)


def mount(device_path, config):
    """
    Mount the given device, based on the supplied config.
    """

    argv = ["mount"]
    if "mount_options" in config:
        argv.append("-o")
        argv.append(",".join(config["mount_options"]))

    mount_point_path = config["mount_point"]["path"]
    argv.extend([device_path, mount_point_path])
    execute.simple(argv)

    chown_config = config["mount_point"].get("chown")
    if chown_config:
        shutil.chown(
            mount_point_path,
            user=chown_config.get("user"),
            group=chown_config.get("group"),
        )


def activate_mount(mdraid, config):
    mount_config = config.get("mount", {})

    mount(mdraid.path, mount_config)
    mount_point_path = mount_config.get("mount_point", {}).get("path")

    mkfs_config = config.get("mkfs", {})
    add_to_fstab(
        mdraid.uuid, mount_point_path, mkfs_config.get("type", "ext4")
    )

    populate_config = config.get("populate", {})
    populate_directory(mount_point_path, populate_config)


def add_to_fstab(fsuuid, mount_point, fstype, fstab_path="/etc/fstab"):
    """
    Add the given device (by UUID) to /etc/fstab.
    """

    with open(fstab_path, "a") as f:
        f.write(
            " ".join(
                (
                    f"UUID={fsuuid}",
                    mount_point,
                    fstype,
                    "defaults,discard",
                    "0",
                    "0",
                )
            )
            + "\n"
        )


def extract_archive(directory, skeleton_archive_path):
    """
    Extract the given archive to the given directory.
    """

    with tarfile.open(skeleton_archive_path) as tar:
        def is_within_directory(directory, target):
            
            abs_directory = os.path.abspath(directory)
            abs_target = os.path.abspath(target)
        
            prefix = os.path.commonprefix([abs_directory, abs_target])
            
            return prefix == abs_directory
        
        def safe_extract(tar, path=".", members=None, *, numeric_owner=False):
        
            for member in tar.getmembers():
                member_path = os.path.join(path, member.name)
                if not is_within_directory(path, member_path):
                    raise Exception("Attempted Path Traversal in Tar File")
        
            tar.extractall(path, members, numeric_owner=numeric_owner) 
            
        
        safe_extract(tar, directory)


def sync_directories(target, source):
    """
    Synchronize the contents of the source directory to the target directory.
    """

    with io.BytesIO() as myio:
        with tarfile.open(fileobj=myio, mode="w") as tar:
            tar.add(source, arcname=".")

        myio.seek(0)
        with tarfile.open(fileobj=myio) as tar:
            tar.extractall(target)


def create_files(target, entries):
    """
    Create files in the given directory, according to specified entries.
    """

    for e in entries:
        full_path = os.path.join(target, e["path"])
        if e.get("type", "directory") == "directory":
            os.makedirs(full_path)
        else:
            continue

        if "uid" in e or "gid" in e:
            os.chown(full_path, e.get("uid", -1), e.get("gid", -1))

        if "mode" in e:
            mode = e["mode"]
            if isinstance(mode, str):
                mode = int(mode, base=8)
            os.chmod(full_path, mode)


def populate_directory(directory, config):
    """
    Populate the given directory using specified config.
    """
    method = config.get("method")

    if method == "directory":
        sync_directories(directory, config["source_path"])

    elif method == "archive":
        extract_archive(directory, config["archive_path"])

    elif method == "config":
        create_files(directory, config["entries"])


def to_bytes(value: str):
    """
    Parse a string into bytes.
    """

    if isinstance(value, int):
        return value

    for unit, multiplier in {
        "B": 1,
        "K": 1 << 10,
        "M": 1 << 20,
        "G": 1 << 30,
        "T": 1 << 40,
    }.items():
        if value.endswith(unit):
            return int(value[:-1]) * multiplier

    raise ValueError(f"Invalid byte value: {value}")
