import io
import os
import os.path
import tarfile

from ephemeral_storage_setup import execute


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
def mkfs(device_path, config):
    """
    Create a filesystem on the given device, based on the supplied config.
    """

    argv = config.get(
        "command",
        [
            "mkfs.ext4",
            "-L",
            config.get("label", "ephemeral"),
            "-m",
            config.get("reserved_blocks_percentage", 0),
        ],
    )
    argv.append(device_path)
    execute.simple(argv)


@udev_settle
def mount(device_path, config):
    """
    Mount the given device, based on the supplied config.
    """

    argv = ["mount"]
    if "mount_options" in config:
        argv.append("-o")
        argv.append(",".join(config["mount_options"]))

    argv.extend([device_path, config["mount_point"]])
    execute.simple(argv)


@udev_settle
def add_to_fstab(fsuuid, mount_point, fstype):
    """
    Add the given device (by UUID) to /etc/fstab.
    """

    with open("/etc/fstab", "a") as f:
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
        tar.extractall(directory)


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

    if config["method"] == "directory":
        sync_directories(directory, config["source_path"])

    elif config["method"] == "archive":
        extract_archive(directory, config["archive_path"])

    elif config["method"] == "config":
        create_files(directory, config["entries"])
