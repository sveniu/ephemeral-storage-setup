import csv
import json
import os
import os.path
import subprocess
import tempfile

import pytest


@pytest.mark.slow
@pytest.mark.parametrize("disk_count", [1, 2, 5])
def test_integration(pytestconfig, disk_count):
    """
    Run the full program within a QEMU VM.
    """

    # The size of each disk, 1.618 GiB. This value matches the ones used with
    # qemu-img, and the qemu/config.yml file.
    disk_size_bytes = 1_737_314_304

    with tempfile.TemporaryDirectory() as tmpdirname:
        env = os.environ.copy()
        env.update(
            {
                "DISK_SIZE_BYTES": f"{disk_size_bytes}",
                "DISK_COUNT": f"{disk_count}",
                "TEMPDIR": tmpdirname,
            }
        )

        subprocess.check_call(
            [
                str(pytestconfig.rootpath / "tests" / "qemu" / "run.sh"),
            ],
            env=env,
        )

        # Verify the result.
        with open(os.path.join(tmpdirname, "lsblk.json")) as f:
            lsblk = json.loads(f.read())

        # Iterate three levels deep (disk, partition, md) to find the expected
        # md device.
        md_device = None
        parent_device_count = 0
        for device in lsblk["blockdevices"]:
            if "children" not in device:
                continue

            for child in device["children"]:
                if "children" not in child:
                    continue

                for grandchild in child["children"]:
                    if grandchild["label"] == "ephemeral":
                        parent_device_count += 1
                        md_device = grandchild

        if md_device is None:
            raise Exception("no ephemeral device found")

        assert parent_device_count == disk_count
        assert md_device["size"] <= disk_size_bytes * disk_count
        assert md_device["size"] >= disk_size_bytes * disk_count * 0.95
        assert md_device["type"] == "raid0"

        got_entries = []
        with open(os.path.join(tmpdirname, "find-mountpoint.csv")) as f:
            reader = csv.DictReader(f, fieldnames=("user", "group", "mode", "path"))
            for row in reader:
                got_entries.append(row)

        for expected_entry in (
            {
                "path": "/mnt/some/deep/path",
                "mode": "750",
            },
        ):
            for entry in got_entries:
                if entry["path"] == expected_entry["path"]:
                    assert entry["mode"] == expected_entry["mode"]
                    break
            else:
                raise Exception(f"{expected_entry['path']} not found in {got_entries}")
