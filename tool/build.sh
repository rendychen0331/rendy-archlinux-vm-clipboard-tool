#!/usr/bin/env bash
# Build the backdoor helper and grant it CAP_SYS_RAWIO (needed for iopl(3),
# so the daemon runs as a normal user, no root). Re-run after any code change:
# the capability is lost when the binary is replaced.
#
# Needs: gcc, rustc, sudo (only for setcap).
set -euo pipefail
cd "$(dirname "$0")"

cc -c rustsrc/backdoor.s -o rustsrc/backdoor.o
rustc -O -C link-arg="$PWD/rustsrc/backdoor.o" rustsrc/main.rs -o backdoor_helper
rm -f rustsrc/backdoor.o

sudo setcap cap_sys_rawio+ep "$PWD/backdoor_helper"
echo "[OK] built ./backdoor_helper with CAP_SYS_RAWIO"
getcap "$PWD/backdoor_helper"
