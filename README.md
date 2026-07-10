# clipsync — VMware Arch Linux (Wayland) ↔ Windows 剪貼簿同步

open-vm-tools 的剪貼簿在 GNOME Wayland（Mutter 無 data-control protocol）下不可用。
clipsync 自建同步通道：guest 端走 XWayland 的 X11 selection（Mutter 會自動橋接
X11 ↔ Wayland 剪貼簿），host 端走 Win32 clipboard API，兩端以 TCP 相連，
全事件驅動、零輪詢。

```
Arch guest (GNOME Wayland)                Windows host
┌────────────────────────┐               ┌────────────────────────┐
│ guest/main.py          │   TCP JSON    │ host/main.py           │
│ python-xlib + XFIXES   │ ────────────► │ pywin32                │
│ (經 XWayland)          │ ◄──────────── │ WM_CLIPBOARDUPDATE     │
└────────────────────────┘  guest 主動連  └────────────────────────┘
```

**範圍**：純文字（UTF-8）。圖片、檔案、富文字不支援。

## 安裝 — Windows host

需求：Python 3 + pywin32（`pip install pywin32`）。

```powershell
cd host
python main.py        # 首次執行會產生 config.json
```

編輯 `host\config.json`：

| 欄位 | 說明 |
|---|---|
| `listen_host` | 建議填 VMnet8 虛擬網卡的 IP（`ipconfig` 查 "VMware Network Adapter VMnet8"，通常 `x.x.x.1`），只在 VM 網段收連線。預設 `0.0.0.0` 會聽所有介面 |
| `listen_port` | 預設 `27333` |
| `token` | **必改**，兩端須一致 |

Windows 防火牆若擋連線，放行該 port（建議 scope 限 VMnet8 網段）。

開機自動啟動（簡易版）：`Win+R` → `shell:startup` → 放一個捷徑，目標
`pythonw.exe C:\...\host\main.py`（`pythonw` 無視窗）。

## 安裝 — Arch guest

```bash
sudo pacman -S --needed python-xlib
```

把 `guest/` 整個目錄放到 VM 的 `~/clipsync/`（scp 或共享資料夾）。

```bash
cd ~/clipsync
python main.py        # 首次執行會產生 config.json
```

編輯 `~/clipsync/config.json`：

| 欄位 | 說明 |
|---|---|
| `host_ip` | Windows host 在 NAT 網段的 IP（guest 內 `ip route` 看子網，host 通常是 `x.x.x.1`；注意 `x.x.x.2` 是 NAT gateway，不是 host） |
| `token` | 與 host 端一致 |

常駐（systemd user unit）：

```bash
mkdir -p ~/.config/systemd/user
cp ~/clipsync/deploy/clipsync-guest.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now clipsync-guest.service
```

## 驗證

1. 兩端 daemon 都啟動，log 出現 `client ... connected` / `connected to host`。
2. VM 內任意 app（含 Wayland 原生 Firefox）複製文字 → Windows `Ctrl+V`。
3. Windows 複製 → VM 貼上。
4. 來回多次不應出現內容跳動（echo loop）。

## 除錯

Log 在各自的 `logs/` 目錄，讀取順序：

1. `clipsync-*_YYYYMMDD.err.log` — 只有 WARNING 以上
2. `clipsync-*_YYYYMMDD.task.jsonl` — 每次傳輸一行（方向、狀態、耗時）
3. 用 task_id grep 詳細 log

常見問題：

- guest 連不上：確認 host 防火牆、`listen_host` 是否綁對網卡、token 一致。
- guest 啟動就掛：確認 `echo $DISPLAY` 有值（XWayland）；systemd unit 需在
  圖形登入後啟動（已掛 `graphical-session.target`）。
- 貼上是舊內容：看兩邊 err.log 是否有 `selection fetch timed out` 或
  `clipboard busy`。

## 開發

- 共用模組（`protocol.py`、`loop_guard.py`、`config_loader.py`、
  `logger_setup.py`）在 `host/src` 與 `guest/src` 各有一份逐字相同的副本
  （部署自足）；`tests/test_copies_in_sync.py` 強制兩份一致 —
  改一邊必須同步另一邊。
- 測試：專案根目錄 `python -m pytest tests/`。
