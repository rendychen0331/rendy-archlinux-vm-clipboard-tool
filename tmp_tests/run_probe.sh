#!/usr/bin/env bash
# Build + run the VMware backdoor clipboard probe.
# Run from the tmp_tests/ directory. Needs: gcc, rustc, root (for iopl).
#
#   sudo systemctl stop vmtoolsd     # avoid channel contention (do this first)
#   ./run_probe.sh                   # read host clipboard
#   ./run_probe.sh --write           # also write, then Ctrl+V on Windows
#   sudo systemctl start vmtoolsd    # restore afterwards
set -euo pipefail
cd "$(dirname "$0")"

cc -c backdoor.s -o backdoor.o
rustc -O -C link-arg="$PWD/backdoor.o" backdoor_probe.rs -o backdoor_probe
echo "[build OK] copy some text on the WINDOWS HOST now, then this runs:"
sudo ./backdoor_probe "$@"
