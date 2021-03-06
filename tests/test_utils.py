import pytest
from ephemeral_storage_setup import utils


def test_mkfs(mocker):
    mock_execute_simple = mocker.patch("ephemeral_storage_setup.execute.simple")
    dev_path = "/dev/foo"
    utils.mkfs(dev_path, {})

    mock_execute_simple.assert_any_call(
        ["mkfs.ext4", "-L", "ephemeral", "-m", "0", dev_path],
    )


def test_mount(mocker):
    mock_execute_simple = mocker.patch("ephemeral_storage_setup.execute.simple")
    dev_path = "/dev/foo"
    config = {"mount_point": "/mnt"}
    utils.mount(dev_path, config)
    mock_execute_simple.assert_any_call(
        ["mount", dev_path, config["mount_point"]],
    )


def test_add_to_fstab(tmpdir):
    file = tmpdir.join("output.txt")
    fsuuid = "12345678-1234-1234-1234-123456789012"
    mount_point = "/mnt"
    fstype = "ext4"
    utils.add_to_fstab(fsuuid, mount_point, fstype, file.strpath)
    output = file.read().strip()
    assert output.startswith(f"UUID={fsuuid} {mount_point} {fstype}")
    assert len(output.split()) == 6


def test_add_to_fstab(tmpdir):
    file = tmpdir.join("output.txt")
    fsuuid = "12345678-1234-1234-1234-123456789012"
    mount_point = "/mnt"
    fstype = "ext4"
    utils.add_to_fstab(fsuuid, mount_point, fstype, file.strpath)
    output = file.read().strip()
    assert output.startswith(f"UUID={fsuuid} {mount_point} {fstype}")
    assert len(output.split()) == 6


@pytest.mark.parametrize(
    "test_input,expected",
    [
        (1, 1),
        ("1B", 1),
        ("1 B", 1),
        ("1K", 1024),
        ("1M", 1024 * 1024),
        ("1G", 1024 * 1024 * 1024),
    ],
)
def test_to_bytes(test_input, expected):
    assert utils.to_bytes(test_input) == expected
