//! clipsync backdoor helper (v2 transport).
//!
//! Talks the VMware low-bandwidth backdoor clipboard channel and bridges it
//! to the Python X11 side over stdin/stdout:
//!   stdout  "H <hex>\n"  -- host clipboard changed, here is the new text
//!   stdin   "G <hex>\n"  -- guest clipboard changed, write it to the host
//!
//! The register-level call lives in backdoor.s (proven 7-register convention).
//! Data confirmed to arrive in EAX (probe, 2026-07). Needs CAP_SYS_RAWIO for
//! iopl(3); grant it with `setcap cap_sys_rawio+ep` so no root is required.
//!
//! Build: see build.sh (cc backdoor.s + rustc, zero external crates).

use std::arch::asm;
use std::io::{self, BufRead, Write};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

const MAGIC: u32 = 0x564D_5868; // "VMXh"
const PORT_LB: u32 = 0x5658;
const CMD_GETSELLENGTH: u32 = 6;
const CMD_GETNEXTPIECE: u32 = 7;
const CMD_SETSELLENGTH: u32 = 8;
const CMD_SETSELPIECE: u32 = 9;
const CMD_GETVERSION: u32 = 10;
const NO_SELECTION: u32 = 0xFFFF_FFFF;
const MAX_BYTES: u32 = 16 * 1024 * 1024; // sanity cap on a reported length

#[repr(C)]
#[derive(Default, Clone, Copy)]
struct Buf {
    eax: u32,
    ebx: u32,
    ecx: u32,
    edx: u32,
    ebp: u32,
    edi: u32,
    esi: u32,
}

extern "C" {
    fn _vmw_lb_in(arg: *const Buf, res: *mut Buf);
}

fn call(cmd: u32, ebx: u32) -> Buf {
    let arg = Buf { eax: MAGIC, ebx, ecx: cmd, edx: PORT_LB, ..Default::default() };
    let mut res = Buf::default();
    unsafe { _vmw_lb_in(&arg, &mut res) };
    res
}

fn iopl3() -> i64 {
    let ret: i64;
    unsafe {
        asm!("syscall", inlateout("rax") 172i64 => ret, in("rdi") 3i64,
             out("rcx") _, out("r11") _, options(nostack));
    }
    ret
}

/// Read the host clipboard. None if empty / no selection / implausible length.
/// Caller must hold the backdoor lock for the whole GETSELLENGTH+pieces run.
fn read_host() -> Option<Vec<u8>> {
    let len = call(CMD_GETSELLENGTH, 0).eax;
    if len == NO_SELECTION || len == 0 || len > MAX_BYTES {
        return None;
    }
    let mut buf = Vec::with_capacity(len as usize);
    for _ in 0..len.div_ceil(4) {
        buf.extend_from_slice(&call(CMD_GETNEXTPIECE, 0).eax.to_le_bytes());
    }
    buf.truncate(len as usize);
    Some(buf)
}

/// Write the host clipboard. Caller must hold the backdoor lock.
fn write_host(data: &[u8]) {
    call(CMD_SETSELLENGTH, data.len() as u32);
    for chunk in data.chunks(4) {
        let mut w = [0u8; 4];
        w[..chunk.len()].copy_from_slice(chunk);
        call(CMD_SETSELPIECE, u32::from_le_bytes(w));
    }
}

fn to_hex(data: &[u8]) -> String {
    let mut s = String::with_capacity(data.len() * 2);
    for b in data {
        s.push(char::from_digit((b >> 4) as u32, 16).unwrap());
        s.push(char::from_digit((b & 0xf) as u32, 16).unwrap());
    }
    s
}

fn from_hex(s: &str) -> Option<Vec<u8>> {
    let s = s.trim();
    if s.len() % 2 != 0 {
        return None;
    }
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(s.len() / 2);
    for pair in b.chunks(2) {
        let hi = (pair[0] as char).to_digit(16)?;
        let lo = (pair[1] as char).to_digit(16)?;
        out.push((hi * 16 + lo) as u8);
    }
    Some(out)
}

fn log(msg: &str) {
    eprintln!("[helper] {msg}");
}

/// Shared state: the backdoor lock also guards `last` (last host content seen
/// or written), so a poll never interleaves with a write and our own writes
/// are not echoed back to the guest.
struct State {
    last: Vec<u8>,
}

fn main() {
    let poll_ms: u64 = std::env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(400);

    if iopl3() < 0 {
        log("iopl(3) failed: need CAP_SYS_RAWIO. Run:");
        log("  sudo setcap cap_sys_rawio+ep <this binary>");
        std::process::exit(1);
    }
    let v = call(CMD_GETVERSION, 0);
    if v.ebx != MAGIC {
        log("backdoor did not answer (ebx != VMXh); not a VMware guest?");
        std::process::exit(1);
    }
    log(&format!("ready, polling host clipboard every {poll_ms}ms"));

    let state = Arc::new(Mutex::new(State { last: Vec::new() }));

    // Poll thread: host clipboard -> stdout.
    let poll_state = Arc::clone(&state);
    thread::spawn(move || loop {
        thread::sleep(Duration::from_millis(poll_ms));
        let emit = {
            let mut s = poll_state.lock().unwrap();
            match read_host() {
                Some(data) if data != s.last => {
                    s.last = data.clone();
                    Some(data)
                }
                _ => None,
            }
        };
        if let Some(data) = emit {
            let mut out = io::stdout().lock();
            let _ = writeln!(out, "H {}", to_hex(&data));
            let _ = out.flush();
        }
    });

    // Main thread: stdin -> host clipboard.
    let stdin = io::stdin();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        if let Some(hex) = line.strip_prefix("G ") {
            match from_hex(hex) {
                Some(data) => {
                    let mut s = state.lock().unwrap();
                    write_host(&data);
                    s.last = data; // suppress the echo on the next poll
                }
                None => log("bad hex on stdin, ignored"),
            }
        }
    }
}
