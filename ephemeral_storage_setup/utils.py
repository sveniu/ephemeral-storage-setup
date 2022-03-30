import io
import tarfile

import execute


def mkfs(device_path, config):
    argv = config.get(
        "argv",
        [
            "mkfs.ext4",
            "-L",
            "ephemeral",
            "-m",
            "0",
        ],
    )
    argv.append(device_path)
    execute.simple(argv)


def mount(device_path, config):
    argv = ["mount"]
    if "mount_options" in config:
        argv.append("-o")
        argv.append(",".join(config["mount_options"]))

    argv.extend([device_path, config["mount_point"]])
    execute.simple(argv)


def add_to_fstab(fsuuid, mount_point, fstype):
    with open("/etc/fstab", "a") as f:
        f.write(
            " ".join(
                f"UUID={fsuuid}",
                mount_point,
                fstype,
                "defaults,discard",
                "0",
                "0",
            )
            + "\n"
        )


def extract_skeleton(directory, skeleton_archive_path):
    with tarfile.open(skeleton_archive_path) as tar:
        tar.extractall(directory)


def sync_directories(target, source):
    with io.BytesIO() as myio:
        with tarfile.open(fileobj=myio, mode="w") as tar:
            # FIXME strip first component?
            tar.add(source)

        myio.seek(0)
        with tarfile.open(fileobj=myio) as tar:
            tar.extractall(target)


def populate_directory(directory, config):
    if config["method"] == "archive":
        extract_skeleton(directory, config["archive_path"])

    if config["method"] == "directory":
        sync_directories(directory, config["source_path"])
