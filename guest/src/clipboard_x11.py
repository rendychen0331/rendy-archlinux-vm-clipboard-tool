"""X11 CLIPBOARD selection watcher/owner via XFIXES, for XWayland.

Runs against the XWayland server inside a GNOME Wayland session; Mutter
bridges the X11 CLIPBOARD selection to/from native Wayland apps in both
directions, so owning/reading the X selection covers the whole desktop.

- Watch: XFixesSelectSelectionInput fires on every CLIPBOARD owner change;
  we then ConvertSelection(UTF8_STRING) and read the property (INCR-aware).
- Own: on set_text() we take selection ownership and answer
  SelectionRequest events (TARGETS / UTF8_STRING / text/plain / STRING).

Single-threaded event loop over select(); set_text() may be called from
any thread (wakes the loop via a socketpair).
"""
import logging
import select
import socket
import threading
import time

from Xlib import X, Xatom, display
from Xlib.ext import xfixes
from Xlib.protocol import event as xevent

FETCH_TIMEOUT = 2.0
PROP_WRITE_CHUNK = 60000  # stay under the X11 max request size


class X11Clipboard:
    def __init__(self, on_text, max_text_bytes: int = 1048576):
        self._on_text = on_text
        self._max = max_text_bytes
        self._own_data = None   # utf-8 bytes we currently serve, or None
        self._pending = []      # texts queued by set_text (any thread)
        self._lock = threading.Lock()
        self._wake_r, self._wake_w = socket.socketpair()
        self._fetch = None      # in-progress selection fetch state

        self._disp = display.Display()
        screen = self._disp.screen()
        self._win = screen.root.create_window(
            0, 0, 1, 1, 0, screen.root_depth,
            event_mask=X.PropertyChangeMask)
        self._win.set_wm_name("clipsync-guest")

        self.A_CLIPBOARD = self._disp.intern_atom("CLIPBOARD")
        self.A_UTF8 = self._disp.intern_atom("UTF8_STRING")
        self.A_TARGETS = self._disp.intern_atom("TARGETS")
        self.A_TEXT_PLAIN = self._disp.intern_atom("text/plain;charset=utf-8")
        self.A_PROP = self._disp.intern_atom("CLIPSYNC_BUF")
        self.A_INCR = self._disp.intern_atom("INCR")

        self._disp.xfixes_query_version()
        self._disp.xfixes_select_selection_input(
            self._win, self.A_CLIPBOARD,
            xfixes.XFixesSetSelectionOwnerNotifyMask)
        self._disp.flush()
        logging.info("X11 clipboard watcher ready (window 0x%x)",
                     self._win.id)

    # ---- public API (any thread) ----

    def set_text(self, text: str) -> None:
        with self._lock:
            self._pending.append(text)
        self._wake_w.send(b"\x00")

    def run_forever(self) -> None:
        x_fd = self._disp.fileno()
        while True:
            timeout = None
            if self._fetch is not None:
                timeout = max(0.0,
                              self._fetch["deadline"] - time.monotonic())
            r, _, _ = select.select([x_fd, self._wake_r], [], [], timeout)
            if self._wake_r in r:
                self._wake_r.recv(64)
                self._apply_pending()
            if x_fd in r:
                while self._disp.pending_events():
                    self._handle_event(self._disp.next_event())
            if (self._fetch is not None
                    and time.monotonic() >= self._fetch["deadline"]):
                logging.warning("selection fetch timed out")
                self._fetch = None

    # ---- owning the selection ----

    def _apply_pending(self):
        with self._lock:
            if not self._pending:
                return
            text = self._pending[-1]  # only the newest matters
            self._pending.clear()
        self._own_data = text.encode("utf-8")
        self._win.set_selection_owner(self.A_CLIPBOARD, X.CurrentTime)
        self._disp.flush()
        owner = self._disp.get_selection_owner(self.A_CLIPBOARD)
        if getattr(owner, "id", owner) != self._win.id:
            logging.warning("failed to take CLIPBOARD ownership")
        else:
            logging.info("owning CLIPBOARD with %d bytes",
                         len(self._own_data))

    def _serve_request(self, ev):
        prop = ev.property if ev.property else ev.target
        ok = False
        if ev.selection == self.A_CLIPBOARD and self._own_data is not None:
            if ev.target == self.A_TARGETS:
                targets = [self.A_TARGETS, self.A_UTF8,
                           self.A_TEXT_PLAIN, Xatom.STRING]
                ev.requestor.change_property(prop, Xatom.ATOM, 32, targets)
                ok = True
            elif ev.target in (self.A_UTF8, self.A_TEXT_PLAIN,
                               Xatom.STRING):
                self._write_property(ev.requestor, prop, ev.target,
                                     self._own_data)
                ok = True
        resp = xevent.SelectionNotify(
            time=ev.time, requestor=ev.requestor, selection=ev.selection,
            target=ev.target, property=prop if ok else X.NONE)
        ev.requestor.send_event(resp)
        self._disp.flush()

    def _write_property(self, win, prop, ptype, data):
        # Chunked with PropModeAppend so large texts fit within the
        # X11 max request size without needing INCR on the write side.
        win.change_property(prop, ptype, 8, data[:PROP_WRITE_CHUNK])
        for i in range(PROP_WRITE_CHUNK, len(data), PROP_WRITE_CHUNK):
            win.change_property(prop, ptype, 8,
                                data[i:i + PROP_WRITE_CHUNK],
                                X.PropModeAppend)

    # ---- watching / fetching foreign selections ----

    def _handle_event(self, ev):
        logging.debug("x event: %s", type(ev).__name__)
        if isinstance(ev, xfixes.SetSelectionOwnerNotify):
            owner_id = getattr(ev.owner, "id", ev.owner)
            logging.debug("xfixes owner-notify: selection=%s owner=0x%x "
                          "(self=0x%x)", ev.selection, owner_id or 0,
                          self._win.id)
            if ev.selection != self.A_CLIPBOARD:
                return
            if not owner_id or owner_id == self._win.id:
                return  # cleared, or our own set_text
            self._start_fetch()
        elif ev.type == X.SelectionNotify:
            self._on_selection_notify(ev)
        elif ev.type == X.PropertyNotify:
            self._on_property_notify(ev)
        elif ev.type == X.SelectionRequest:
            self._serve_request(ev)
        elif ev.type == X.SelectionClear:
            logging.info("lost CLIPBOARD ownership to another client")
            self._own_data = None

    def _start_fetch(self, target=None):
        target = target or self.A_UTF8
        logging.debug("start fetch: convert_selection target=%s", target)
        self._win.convert_selection(
            self.A_CLIPBOARD, target, self.A_PROP, X.CurrentTime)
        self._disp.flush()
        self._fetch = {"stage": "notify", "target": target, "buf": b"",
                       "deadline": time.monotonic() + FETCH_TIMEOUT}

    def _on_selection_notify(self, ev):
        if self._fetch is None or self._fetch["stage"] != "notify":
            return
        if not ev.property:  # owner does not support this target
            if self._fetch["target"] == self.A_UTF8:
                logging.debug("UTF8_STRING refused, retrying with STRING")
                self._start_fetch(Xatom.STRING)
            else:
                logging.warning("selection owner offers no text target")
                self._fetch = None
            return
        prop = self._win.get_full_property(self.A_PROP, X.AnyPropertyType)
        self._win.delete_property(self.A_PROP)
        self._disp.flush()
        if prop is None:
            self._fetch = None
            return
        if prop.property_type == self.A_INCR:
            # INCR transfer: deleting the property (above) tells the owner
            # to start sending chunks via PropertyNotify.
            self._fetch["stage"] = "incr"
            self._fetch["deadline"] = time.monotonic() + FETCH_TIMEOUT
            return
        self._finish_fetch(self._as_bytes(prop.value))

    def _on_property_notify(self, ev):
        if (self._fetch is None or self._fetch["stage"] != "incr"
                or ev.atom != self.A_PROP
                or ev.state != X.PropertyNewValue):
            return
        prop = self._win.get_full_property(self.A_PROP, X.AnyPropertyType)
        self._win.delete_property(self.A_PROP)
        self._disp.flush()
        chunk = self._as_bytes(prop.value) if prop else b""
        if not chunk:
            self._finish_fetch(self._fetch["buf"])
            return
        self._fetch["buf"] += chunk
        self._fetch["deadline"] = time.monotonic() + FETCH_TIMEOUT
        if len(self._fetch["buf"]) > self._max:
            logging.warning("INCR transfer exceeds max_text_bytes, aborted")
            self._fetch = None

    def _finish_fetch(self, data: bytes):
        self._fetch = None
        logging.debug("fetch finished: %d bytes", len(data))
        if not data:
            return
        if len(data) > self._max:
            logging.warning("clipboard text exceeds max_text_bytes, skipped")
            return
        text = data.decode("utf-8", errors="replace")
        try:
            self._on_text(text)
        except Exception:
            logging.exception("clipboard text handler failed")

    @staticmethod
    def _as_bytes(value):
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("latin-1", errors="replace")
        return bytes(value)
