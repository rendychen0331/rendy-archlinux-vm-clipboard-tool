# rendy-archlinux-vm-clipboard-tool

[繁體中文](README.zh-TW.md)

Clipboard sync between a VMware Arch Linux (Wayland) guest and its Windows host.

open-vm-tools' clipboard does not work under GNOME Wayland (Mutter has no
data-control protocol). This tool talks the VMware backdoor channel directly to
exchange the clipboard with the hypervisor — so **nothing needs to be installed
on Windows** (VMware handles the host clipboard half itself).

```
Arch guest (GNOME Wayland)                    Windows host
┌──────────────────────────┐                 ┌──────────────────┐
│ main.py (python-xlib)     │  stdin/stdout   │ handled by VMware │
│   ↕                       │  hex lines      │ host clipboard    │
│ backdoor_helper (Rust)    │ ──backdoor────► │ (nothing to set up)│
└──────────────────────────┘   VMXh 0x5658    └──────────────────┘
```

- **Guest side**: uses the X11 CLIPBOARD selection under XWayland (Mutter bridges
  X11 ↔ Wayland automatically, so Wayland-native apps like Firefox are covered).
- **Transport**: a Rust helper speaks the VMware low-bandwidth backdoor clipboard
  protocol (`GETSELLENGTH` / `GETNEXTPIECE` / `SETSEL*`), polls the host
  clipboard, and bridges to Python over stdin/stdout hex lines.
- **Privilege**: the backdoor needs `iopl(3)`, so the helper carries the
  `CAP_SYS_RAWIO` file capability (`build.sh` sets it automatically). A normal
  user is enough — **no root**.
- **Scope**: plain text (UTF-8). Images, files, and rich text are not supported.

## Install

On the VM (Arch guest):

```bash
sudo pacman -S --needed python-xlib gcc rust
# put the whole tool/ directory at ~/clipsync-tool/
cd ~/clipsync-tool
bash build.sh         # builds backdoor_helper and setcap cap_sys_rawio+ep
python main.py        # first run creates config.json
```

`config.json` fields: `poll_ms` (poll interval, default 400), `max_text_bytes`,
`log_level`, `helper_bin` (default `backdoor_helper`). Usually no need to change.

vmtoolsd may stay running — verified to coexist with this tool (its clipboard is
inert under Wayland, so it does not actually consume the backdoor channel;
shared folders / time sync keep working).

## Autostart (systemd user unit)

```bash
mkdir -p ~/.config/systemd/user
cp ~/clipsync-tool/deploy/clipsync-tool.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now clipsync-tool.service
```

Note: the capability is lost whenever the binary is rebuilt, so re-run
`bash build.sh` after any Rust change (it re-applies setcap).

## Verify

1. The daemon starts; the log shows `X11 clipboard watcher ready` and
   `helper: ready`.
2. Copy text in any VM app (including Wayland-native Firefox) → paste on Windows.
3. Copy on Windows → paste in the VM.
4. Repeated round-trips must not show content flapping (echo loop).

## Troubleshooting

Logs live in `logs/`, read in this order:

1. `clipsync-tool_YYYYMMDD.err.log` — WARNING and above only
2. `clipsync-tool_YYYYMMDD.task.jsonl` — one line per transfer (direction,
   status, duration)
3. grep the detail log by task_id; set `log_level` to `DEBUG` for X11 event
   detail

Common issues:

- guest→host does nothing: check for `guest->host N chars` under `DEBUG`.
  GNOME 50.3 Mutter does not deliver the XFIXES owner-notify, so detection falls
  back to SelectionClear + a 600ms owner poll.
- helper won't start / `need CAP_SYS_RAWIO`: re-run `bash build.sh` (a rebuild
  drops the capability).
- paste yields stale content: check err.log for `selection fetch timed out`.

## Development

- Python side: `src/clipboard_x11.py`, `config_loader.py`, `logger_setup.py`.
  Rust helper: `rustsrc/` (`backdoor.s` + `main.rs`).
- The backdoor call uses a standalone `.s` (the proven 7-register convention
  from lucab/vmw_backdoor).
- `tmp_tests/`: the backdoor probe (`backdoor_probe.rs` + `run_probe.sh`). If a
  future VMware upgrade breaks v2, `bash tmp_tests/run_probe.sh` tells in one
  shot whether the backdoor channel itself changed or the daemon logic did. The
  probe assembles `tool/rustsrc/backdoor.s` directly (single source, no copy).
