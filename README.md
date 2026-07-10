# clipsync — VMware Arch Linux (Wayland) ↔ Windows 剪貼簿同步

open-vm-tools 的剪貼簿在 GNOME Wayland（Mutter 無 data-control protocol）下不可用。
本專案自建同步通道。guest 端都走 XWayland 的 X11 CLIPBOARD selection（Mutter
自動橋接 X11 ↔ Wayland，Wayland 原生 app 也涵蓋）；差別在跟 Windows 之間怎麼傳：

| | v1 `host/` + `guest/` | v2 `tool/`（推薦） |
|---|---|---|
| 通道 | 自建 TCP（NAT 內網） | VMware backdoor（免網路） |
| Windows 端 | 要跑 host daemon | **不用**，VMware 自己處理 host 剪貼簿 |
| 事件模型 | 兩端事件推送 | guest 端輪詢 backdoor（~400ms） |
| 權限 | 一般 user | helper 需 `CAP_SYS_RAWIO`（`setcap`，非 root） |
| 語言 | 純 Python | Python + Rust helper |

v2 是專案主目標（repo 名 `-tool`）。v1 保留作為 fallback / 參考。
兩者都只做純文字（UTF-8）；圖片、檔案、富文字不支援。

---

## v2 安裝 — `tool/`（backdoor，免 host daemon）

VM（Arch guest）內：

```bash
sudo pacman -S --needed python-xlib gcc rust
# 把 tool/ 放到 ~/clipsync-tool/
cd ~/clipsync-tool
./build.sh            # 編譯 backdoor_helper 並 setcap cap_sys_rawio+ep
python main.py        # 首次執行產生 config.json
```

`config.json` 欄位：`poll_ms`(輪詢間隔)、`max_text_bytes`、`log_level`、
`helper_bin`(預設 `backdoor_helper`)。通常不用改。

vmtoolsd 可以繼續開著（實測與 v2 並存不衝突 —— vmtoolsd 的剪貼簿在 Wayland
下本來就不作用，不會真的消費 backdoor 通道；共享資料夾 / time sync 照常）。

常駐（systemd user unit）：

```bash
mkdir -p ~/.config/systemd/user
cp ~/clipsync-tool/deploy/clipsync-tool.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now clipsync-tool.service
```

注意：`build.sh` 重編後 capability 會消失，須重跑（會自動 setcap）。

---

## v1 安裝 — `host/` + `guest/`（TCP fallback）

v1 走的是網路，跟 open-vm-tools 完全不同通道。
guest 端走 XWayland 的 X11 selection，host 端走 Win32 clipboard API，
兩端以 TCP 相連，全事件驅動、零輪詢。

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
