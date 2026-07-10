# rendy-archlinux-vm-clipboard-tool

[English](README.md)

VMware Arch Linux (Wayland) ↔ Windows 剪貼簿同步。

open-vm-tools 的剪貼簿在 GNOME Wayland（Mutter 無 data-control protocol）下不可用。
本工具改走 VMware backdoor 通道直接跟 hypervisor 交換剪貼簿 —— **Windows 端完全
不用裝任何東西**（VMware 自己處理 host 剪貼簿那半）。

```
Arch guest (GNOME Wayland)                    Windows host
┌──────────────────────────┐                 ┌──────────────────┐
│ main.py (python-xlib)     │  stdin/stdout   │ VMware 自己處理   │
│   ↕                       │  hex lines      │ host clipboard   │
│ backdoor_helper (Rust)    │ ──backdoor────► │ (免安裝)         │
└──────────────────────────┘   VMXh 0x5658    └──────────────────┘
```

- **guest 端**：走 XWayland 的 X11 CLIPBOARD selection（Mutter 自動橋接
  X11 ↔ Wayland，Wayland 原生 app 如 Firefox 也涵蓋）。
- **transport**：Rust helper 講 VMware low-bandwidth backdoor 剪貼簿協議
  （`GETSELLENGTH`/`GETNEXTPIECE`/`SETSEL*`），輪詢 host 剪貼簿，經 stdin/stdout
  hex line 橋接到 Python。
- **權限**：backdoor 需 `iopl(3)` → helper 帶檔案能力 `CAP_SYS_RAWIO`
  （`build.sh` 自動 setcap），一般 user 即可，**不用 root**。
- **範圍**：純文字（UTF-8）。圖片、檔案、富文字不支援。

## 安裝

全部在 VM（Arch guest）內。三選一。僅 `x86_64`（backdoor 組語限定）。

### A. 從 Releases 裝預編套件（最簡單）

到 [最新 Release](../../releases) 下載 `.pkg.tar.zst`，然後：

```bash
sudo pacman -U rendy-vm-clipboard-git-*.pkg.tar.zst
```

pacman 會裝好 helper（已設 `CAP_SYS_RAWIO`）、systemd user unit，並拉齊依賴。
移除：`pacman -R rendy-vm-clipboard-git`，乾淨。

### B. 從原始碼建套件

```bash
sudo pacman -S --needed git base-devel
git clone https://github.com/rendychen0331/rendy-archlinux-vm-clipboard-tool.git
cd rendy-archlinux-vm-clipboard-tool/packaging
makepkg -si        # 編 Rust helper、解依賴、setcap、安裝
```

### C. 手動（不打包，開發用）

```bash
sudo pacman -S --needed python-xlib gcc rust
# 把整個 tool/ 放到 ~/clipsync-tool/
cd ~/clipsync-tool
bash build.sh         # 編譯 backdoor_helper 並 setcap cap_sys_rawio+ep
python main.py        # 首次執行在 main.py 旁產生 config.json
```

### 任一方式裝完 —— 啟用常駐

```bash
systemctl --user enable --now clipsync-tool.service
```

（只有方式 C 要先 `cp deploy/clipsync-tool.service ~/.config/systemd/user/ &&
systemctl --user daemon-reload`；A/B 已幫你裝好 unit。）

`config.json` 欄位：`poll_ms`(輪詢間隔，預設 400)、`max_text_bytes`、
`log_level`、`helper_bin`。通常不用改。套件安裝（A/B）的 config + logs 放在
`~/.config/clipsync-tool` 與 `~/.local/state/clipsync-tool`；手動（C）放在
`main.py` 旁邊。

vmtoolsd 可以繼續開著（實測與本工具並存不衝突 —— vmtoolsd 的剪貼簿在 Wayland
下本來就不作用，不會真的消費 backdoor 通道；共享資料夾 / time sync 照常）。

注意：helper 重編後 `CAP_SYS_RAWIO` 會消失。套件在每次安裝/升級會自動重設；
方式 C 則要在改動 Rust 後重跑 `bash build.sh`。

## 驗證

1. daemon 啟動，log 出現 `X11 clipboard watcher ready` 與 `helper: ready`。
2. VM 內任意 app（含 Wayland 原生 Firefox）複製文字 → Windows `Ctrl+V`。
3. Windows 複製 → VM 貼上。
4. 來回多次不應出現內容跳動（echo loop）。

## 除錯

Log 在 `logs/`，讀取順序：

1. `clipsync-tool_YYYYMMDD.err.log` — 只有 WARNING 以上
2. `clipsync-tool_YYYYMMDD.task.jsonl` — 每次傳輸一行（方向、狀態、耗時）
3. 用 task_id grep 詳細 log；`log_level` 設 `DEBUG` 看 X11 事件細節

常見問題：

- guest→host 沒反應：`DEBUG` 下看有沒有 `guest->host N chars`。GNOME 50.3 的
  Mutter 不送 XFIXES owner-notify，偵測改靠 SelectionClear + 600ms owner 輪詢。
- helper 起不來 / `need CAP_SYS_RAWIO`：重跑 `bash build.sh`（重編會掉 cap）。
- 貼上是舊內容：看 err.log 有沒有 `selection fetch timed out`。

## 開發

- Python 端：`src/clipboard_x11.py`、`config_loader.py`、`logger_setup.py`；
  Rust helper：`rustsrc/`（`backdoor.s` + `main.rs`）。
- backdoor 呼叫用獨立 `.s`（proven 7-register 慣例，出處 lucab/vmw_backdoor）。
- `tmp_tests/`：backdoor probe（`backdoor_probe.rs` + `run_probe.sh`）。未來
  VMware 升級後若 v2 壞了，`bash tmp_tests/run_probe.sh` 能一秒分辨是 backdoor
  通道本身變了、還是 daemon 邏輯問題。probe 直接組譯 `tool/rustsrc/backdoor.s`
  （單一來源，不另存副本）。
