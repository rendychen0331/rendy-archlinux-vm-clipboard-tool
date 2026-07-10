//! VMware backdoor probe: answers the two questions that gate the
//! rendy-archlinux-vm-clipboard-tool design.
//!
//!   1. Can userspace reach the backdoor, and does it need root?
//!   2. Are the legacy clipboard selection commands still alive on this
//!      VMware build?
//!
//! Build (no cargo, no crates):
//!     rustc -O backdoor_probe.rs -o backdoor_probe
//! Run:
//!     ./backdoor_probe              # read-only probe
//!     sudo ./backdoor_probe         # retry with root if iopl fails
//!     sudo ./backdoor_probe --write # also push text to the host clipboard
//!
//! Protocol: eax=magic, ebx=param, ecx=command, dx=port, then `in eax, dx`.
//! The hypervisor traps the instruction and returns values in eax/ebx/ecx/edx.
//! Command numbers are from open-vm-tools backdoor_def.h.

use std::arch::asm;

const MAGIC: u32 = 0x564D_5868; // "VMXh"
const PORT: u32 = 0x5658; // "VX"

const CMD_GETSELLENGTH: u32 = 6;
const CMD_GETNEXTPIECE: u32 = 7;
const CMD_SETSELLENGTH: u32 = 8;
const CMD_SETSELPIECE: u32 = 9;
const CMD_GETVERSION: u32 = 10;

const NO_SELECTION: u32 = 0xFFFF_FFFF;
const SYS_IOPL: i64 = 172;

/// iopl(2) raw syscall. ioperm() cannot be used: it only covers ports
/// 0x000-0x3FF and the backdoor lives at 0x5658.
unsafe fn iopl(level: i64) -> i64 {
    let ret: i64;
    asm!(
        "syscall",
        inlateout("rax") SYS_IOPL => ret,
        in("rdi") level,
        out("rcx") _,
        out("r11") _,
        options(nostack)
    );
    ret
}

/// One backdoor call. rbx is reserved by LLVM, so swap it in and out
/// around the `in` instruction rather than naming it directly.
unsafe fn bdoor(cmd: u32, param: u32) -> (u32, u32, u32, u32) {
    let mut eax: u32 = MAGIC;
    let mut ebx: u32 = param;
    let mut ecx: u32 = cmd;
    let mut edx: u32 = PORT;
    asm!(
        "xchg {tmp:e}, ebx",
        "in eax, dx",
        "xchg {tmp:e}, ebx",
        tmp = inout(reg) ebx,
        inout("eax") eax,
        inout("ecx") ecx,
        inout("edx") edx,
        options(nostack)
    );
    (eax, ebx, ecx, edx)
}

fn step(n: u32, what: &str) {
    println!("\n--- step {n}: {what} ---");
}

fn main() {
    let write_test = std::env::args().any(|a| a == "--write");
    let uid = unsafe {
        let r: i64;
        asm!("syscall", inlateout("rax") 102i64 => r, out("rcx") _,
             out("r11") _, options(nostack));
        r
    };
    println!("running as uid={uid}");

    step(1, "iopl(3) -- I/O port permission");
    let rc = unsafe { iopl(3) };
    if rc < 0 {
        println!("[FAIL] iopl(3) returned {rc} (errno {})", -rc);
        if uid != 0 {
            println!("       -> almost certainly EPERM (-1). Re-run with sudo.");
        } else {
            println!("       -> failed even as root. Backdoor via raw I/O is");
            println!("          not available on this kernel/config.");
        }
        std::process::exit(1);
    }
    println!("[OK] iopl(3) granted{}", if uid == 0 { " (as root)" } else { " WITHOUT root -- good news" });

    step(2, "GETVERSION -- are we really inside VMware?");
    let (ver, magic, product, _) = unsafe { bdoor(CMD_GETVERSION, 0) };
    println!("eax(version)=0x{ver:08X}  ebx(magic)=0x{magic:08X}  ecx(product)=0x{product:08X}");
    if magic != MAGIC {
        println!("[FAIL] ebx != VMXh -- backdoor did not answer. Not a VMware");
        println!("       guest, or the backdoor is disabled.");
        std::process::exit(1);
    }
    println!("[OK] backdoor responds");

    step(3, "GETSELLENGTH -- is the legacy clipboard channel alive?");
    println!("(copy some text on the WINDOWS HOST first, then run this)");
    let (len, ..) = unsafe { bdoor(CMD_GETSELLENGTH, 0) };
    if len == NO_SELECTION {
        println!("[WARNING] returned 0xFFFFFFFF = no selection available.");
        println!("          Either the host clipboard is empty/non-text, or");
        println!("          this VMware build dropped the legacy protocol.");
        println!("          Copy text on the host and re-run before concluding.");
    } else if len == 0 {
        println!("[WARNING] length 0 -- channel answers but host clipboard is empty.");
        println!("          Channel looks ALIVE. Copy text on the host and re-run.");
    } else {
        println!("[OK] host clipboard reports {len} bytes -- channel ALIVE");
        step(4, "GETNEXTPIECE -- read the host clipboard");
        let mut buf: Vec<u8> = Vec::with_capacity(len as usize);
        let words = len.div_ceil(4);
        for _ in 0..words {
            let (piece, ..) = unsafe { bdoor(CMD_GETNEXTPIECE, 0) };
            buf.extend_from_slice(&piece.to_le_bytes());
        }
        buf.truncate(len as usize);
        println!("raw bytes: {:02X?}", &buf[..buf.len().min(32)]);
        println!("as text  : {:?}", String::from_utf8_lossy(&buf));
        println!("[OK] read path works");
    }

    if write_test {
        step(5, "SETSELLENGTH + SETSELPIECE -- write to the host clipboard");
        let payload = b"clipsync backdoor probe OK";
        let (_, _, _, _) = unsafe { bdoor(CMD_SETSELLENGTH, payload.len() as u32) };
        for chunk in payload.chunks(4) {
            let mut word = [0u8; 4];
            word[..chunk.len()].copy_from_slice(chunk);
            unsafe { bdoor(CMD_SETSELPIECE, u32::from_le_bytes(word)) };
        }
        println!("[OK] wrote {} bytes. Now press Ctrl+V on the WINDOWS HOST.", payload.len());
        println!("     Expect: clipsync backdoor probe OK");
        println!("     If nothing pastes, the write path is dead on this build.");
    } else {
        println!("\n(skipped write test; re-run with --write to test host<-guest)");
    }

    println!("\n=== summary ===");
    println!("Paste this whole output back. It decides whether");
    println!("rendy-archlinux-vm-clipboard-tool can drop the host daemon.");
}
