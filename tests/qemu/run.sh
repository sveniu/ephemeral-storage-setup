#!/bin/sh

# This script prepares and runs a QEMU virtual machine to integration test the
# ephemeral-storage-setup program. It uses tar archives written to (and read
# from) block devices, to be able to pass data into and out of the VM.
#
# Based on: https://powersj.io/posts/ubuntu-qemu-cli/

set -eux

# Check required commands.
for cmd in \
    curl \
    cloud-localds \
    qemu-img \
    qemu-system-x86_64 \
    ; do
  command -v "$cmd" >/dev/null || {
    printf >&2 "Required command not found: %s\n" "$cmd"
    exit 1
  }
done

cache_path="${HOME}/.cache/qemu/images"
imgname="jammy-server-cloudimg-amd64.img"
imgpath="${cache_path}/${imgname}"

if [ ! -d "$cache_path" ]; then
  mkdir -p "$cache_path"
fi
    
if [ ! -f "$imgpath" ]; then
  printf "Downloading image ...\n"
  curl -s -o "$imgpath" "https://cloud-images.ubuntu.com/jammy/20220423/${imgname}"
fi

# Variables from environment.
disk_count=${DISK_COUNT:-2}
disk_size_bytes=${DISK_SIZE_BYTES:-1737314304}

# Temp dir from environment.
if [ -n "$TEMPDIR" -a -d "$TEMPDIR" ]; then
  tmpdir="$TEMPDIR"
  delete_tmpdir="no"
else
  tmpdir=$(mktemp -d)
  delete_tmpdir="yes"
fi

(
  set -eux
  cd "$tmpdir"

  cat > metadata.yaml <<-EOF
instance-id: iid-local01
local-hostname: cloudimg
EOF
  
  cat > user-data.yaml <<EOF
#cloud-config

# Find the block device containing the shared file archive, extract it to a
# temporary directory, and then run the shell script.
runcmd:
  - 'set -x; lsblk --output PATH,SERIAL | while read path serial; do if [ "\$serial" = "QEMU_SHARED_INPUT" ]; then cd \$(mktemp -d) && tar xzf "\$path" && exec ./ephemeral-storage-setup/tests/qemu/run_inside_vm.sh; break; fi; done'

# Power off at the end of cloud-init, after the above command has completed.
power_state:
  mode: poweroff
EOF

  # Generate seed image for cloud-init.
  cloud-localds seed.img user-data.yaml metadata.yaml

  # Create base disk.
  qemu-img create -f qcow2 -o backing_file="$imgpath" base.qcow2

  # Create disks for RAID.
  for i in $(seq 1 "$disk_count"); do
    qemu-img create -f qcow2 disk${i}.qcow2 "$disk_size_bytes"
  done

  # Create two small disks for input and output.
  qemu-img create -f qcow2 shared_input.qcow2 10M
  qemu-img create -f qcow2 shared_output.qcow2 10M
)

# Create shared input archive containing the entire working tree.
tmptar="$tmpdir"/shared_input.tgz

# Find the base path of the project.
base_path=""
for path in \
    . \
    .. \
    ../.. \
    ;
do
  if [ -f "$path"/pyproject.toml ]; then
    base_path="$path"
    break
  fi
done

if [ "$base_path" = "" ]; then
  printf >&2 "Could not find project top-level directory\n"
  exit 1
fi

# Archive the entire project directory, to share it with the VM.
tar --transform 's,^,ephemeral-storage-setup/,' -czf "$tmptar" "$base_path"
qemu-img dd bs=1M if="$tmptar" of="$tmpdir"/shared_input.qcow2

(
  set -eux
  cd "$tmpdir"
  
  # Construct command line.
  cmd="qemu-system-x86_64 -machine accel=kvm,type=q35 -cpu host -m 1G -nographic"
  cmd="${cmd} -drive if=virtio,format=qcow2,file=base.qcow2"
  cmd="${cmd} -drive if=virtio,format=raw,file=seed.img"
  cmd="${cmd} -device megasas,id=scsi0"

  disk_index=0
  for i in $(seq 1 "$disk_count"); do
    cmd="${cmd} -device scsi-hd,drive=drive${disk_index},bus=scsi0.0,channel=0,scsi-id=${disk_index},lun=0"
    cmd="${cmd} -drive file=disk${i}.qcow2,if=none,id=drive${disk_index}"
    disk_index=$(( disk_index + 1 ))
  done

  cmd="${cmd} -device scsi-hd,drive=drive${disk_index},bus=scsi0.0,channel=0,scsi-id=${disk_index},lun=0,serial=QEMU_SHARED_INPUT"
  cmd="${cmd} -drive file=shared_input.qcow2,if=none,id=drive${disk_index}"
  disk_index=$(( disk_index + 1 ))
  cmd="${cmd} -device scsi-hd,drive=drive${disk_index},bus=scsi0.0,channel=0,scsi-id=${disk_index},lun=0,serial=QEMU_SHARED_OUTPUT"
  cmd="${cmd} -drive file=shared_output.qcow2,if=none,id=drive${disk_index}"

  # Run QEMU.
  $cmd

  # Get the output archive from the shared device.
  qemu-img dd bs=1M if=shared_output.qcow2 of=shared_output.tgz
  tar xzvf shared_output.tgz
)

if [ -d "$tmpdir" -a "$delete_tmpdir" = "yes" ]; then
  rm -rf "$tmpdir"
fi
