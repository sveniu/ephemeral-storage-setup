# Ephemeral storage setup

tl;dr: RAID 0, mkfs and mount your ephemeral local SSDs on boot.

The slightly longer story:

- Find ephemeral disks (uninitialized ones with certain characteristics)

- Create a single partition on each (to enable automatic RAID assembly)

- Create a Linux RAID 0 using all partitions (also if only one was found)

- Format the RAID device, using ext4 by default

- Mount the filesystem and optionally add fstab entry

- Create directory structure within the mount point

The primary use case is for elastic (aka cattle or disposable) cloud VMs with
local SSDs and high IO requirements. Are you using Packer-built images and auto
scaling groups for your high-IO workloads? Then this might be for you. *Any
other use is actively discouraged*, since there is – by design – not much
flexibility in disk selection and configuration.

## Installation and Usage

Install like so: `pip install git+https://github.com/sveniu/ephemeral-storage-setup`

Prepare a config file: [config file example](examples/config.yml).

Run like so: `sudo ephemeral-storage-setup config.yml`

Or run at boot: [systemd service example](examples/ephemeral-storage-setup.service).

### Dependencies

The following commands must be available on the system:

- `lsblk`: Scan block devices and get device information.

- `sgdisk`: Create the GPT partition table and partitions.

- `mdadm`: Create MD RAID.

- `mkfs.ext4`: Create filesystem. Can be modified via config.

- `mount`: Mount the filesystem.

## Configuration

See the [config file example](examples/config.yml) for full documentation.

## Details

### Ephemeral disks

A disk is considered ephemeral if it passes a few checks:

- It is reported as a block device of type "disk" by udev/lsblk.

- It has no child devices, like partitions, MD/raid, crypto, lvm, etc.

- It has no filesystem, as reported by the lsblk `fstype` attribute.

- It has no label, as reported by the lsblk `label` attribute.

- It has no UUID, as reported by the lsblk `uuid` attribute.

In addition, the disk must pass some configurable checks:

- The model must match, for example `Amazon EC2 NVMe Instance Storage`.

- The disk size must be between a configurable minimum and maximum.

To inspect a system, use `lsblk --json --output-all | jq .`

Note: It's perfectly fine to use persistent disks too, like the volumes provided
by AWS EBS, for example. Just make sure the model and size filters match.

### Partitioning

Each ephemeral disk gets one partition that fills the disk. The only reason for
dealing with partitions at all, is that the partition type identifier enables
RAID auto-assembly on reboot.

The partition table type is GPT, and the partition type GUID is "Linux RAID":
`a19d880f-05fc-4d3b-a006-743f0f84911e` (aka `0xfd00`).

The partition begins exactly at offset 4 MiB, to reduce the chance of
alignment-related performance issues as much as possible.

### RAID

The default RAID level is 0, aka striping. This gives the highest IO and also
the combined space of all member disks. More resilient levels don't really make
sense, since the VM itself is intended to be disposable. It is still recommended
to monitor disks and the apps that use them, to be able to quickly destroy the
VM in case of issues.

Note: With only a single disk, a RAID is still created. This is merely to keep
things simple and consistent across systems.

### Directory skeleton

The mount point can be populated by a directory skeleton copied from another
directory, a tar archive, or entries in the configuration file. This primes the
mount point for use, either by having configured the applications to use
directories within the mount point, or symlinks that point into it.

See the [config file example](examples/config.yml) for how to do this.

### Run at boot

See the [systemd service example](examples/ephemeral-storage-setup.service) for
a simple example of how to run this at boot.

Another alternative is to run via the cloud-init `bootcmd`, which runs early in
the boot process.

### Reboots

If a reboot preserves local SSD contents: The RAID is auto-assembled, and the
filesystem is mounted automatically (via /etc/fstab). Both AWS and GCP preserve
local SSDs across reboots.

If a reboot loses SSD contents or re-provisions the disks entirely: The disk
setup will be done from scratch. Both AWS and GCP lose local SSD contents if the
VM is stopped and restarted. It is recommended to rather destroy the VM and
create a new one instead, to avoid potential issues.
