import pytest
from ephemeral_storage_setup import devices


@pytest.fixture
def fake_lsblk_output(pytestconfig):
    return open(
        str(pytestconfig.rootpath / "tests" / "resources" / "lsblk_output.json"), "r"
    ).read()


def test_scan_devices(mocker, fake_lsblk_output):
    mocker.patch(
        "ephemeral_storage_setup.devices.get_lsblk_output",
        return_value=fake_lsblk_output,
    )

    devs = devices.scan_devices()

    assert len(devs) > 0
    assert "/dev/nvme0n1" in [dev.path for dev in devs]
