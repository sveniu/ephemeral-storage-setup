#!/bin/sh

# This script runs inside a QEMU virtual machine. It first installs and runs
# ephemeral-storage-setup, then gathers lsblk output and contents of the mount
# point. That information is passed back to the wrapper script, which can then
# verify the results.
#
# This script is executed by cloud-init's runcmd block, as constructed by the
# run.sh wrapper script.

set -eux

# Install pip if not present.
if ! command -v pip3 >/dev/null; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3-pip
fi

# The current working directory is the temporary directory containing shared
# files from the run.sh wrapper script.
pip3 install ./ephemeral-storage-setup
ephemeral-storage-setup ./ephemeral-storage-setup/tests/qemu/config.yml

# Prepare output files.
tmpdir=$(mktemp -d)
lsblk --json --output-all --bytes > "$tmpdir"/lsblk.json
find /mnt -printf '%u,%g,%m,%p\n' > "$tmpdir"/find-mountpoint.csv

# Write output files to shared device.
lsblk --output PATH,SERIAL | while read path serial; do
    if [ "$serial" = "QEMU_SHARED_OUTPUT" ]; then
        ( cd "$tmpdir" && tar -czf "$path" . )
        echo success maybe
        break
    fi
done
