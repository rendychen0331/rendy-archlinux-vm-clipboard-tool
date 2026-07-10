//! VMware backdoor clipboard probe (v2 gate).
//!
//! Confirms the legacy selection channel can be READ and WRITTEN from the
//! guest, which decides whether rendy-archlinux-vm-clipboard-tool can drop
//! the host daemon. The register-level backdoor call lives in backdoor.s
//! (proven convention); this file only sets up the command registers and
//! prints every result register so the data register is found empirically,
//! not guessed.
//!
//! Build (zero crates; needs gcc + rustc):
//!     cc -c backdoor.s -o backdoor.o
//!     rustc -O -C link-arg=backdoor.o backdoor_probe.rs -o backdoor_probe
//! Run (needs root for iopl):
//!     sudo ./backdoor_probe            # read host clipboard
//!     sudo ./backdoor_probe --write    # also write, then Ctrl+V on Windows

use std::arch::asm;

const MAGIC: u32 = 0x564D_5868; // "VMXh"
const PORT_LB: u32 = 0x5658;

const CMD_GETSELLENGTH: u32 = 6;
const CMD_GETNEXTPIECE: u32 = 7;
const CMD_SETSELLENGTH: u32 = 8;
const CMD_SETSELPIECE: u32 = 9;
const CMD_GETVERSION: u32 = 10;

const NO_SELECTION: u32 = 0xFFFF_FFFF;
const MAX_PIECES: u32 = 4096; // guard against a garbage length

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

fn getuid() -> i64 {
    let ret: i64;
    unsafe {
        asm!("syscall", inlateout("rax") 102i64 => ret, out("rcx") _,
             out("r11") _, options(nostack));
    }
    ret
}

fn step(n: u32, what: &str) {
    println!("\n--- step {n}: {what} ---");
}

fn main() {
    let write_test = std::env::args().any(|a| a == "--write");
    println!("running as uid={}", getuid());

    step(1, "iopl(3) -- I/O port permission");
    let rc = iopl3();
    if rc < 0 {
        println!("[FAIL] iopl(3) errno {} -- re-run with sudo", -rc);
        std::process::exit(1);
    }
    println!("[OK] iopl(3) granted");

    step(2, "GETVERSION -- backdoor sanity");
    let r = call(CMD_GETVERSION, 0);
    println!("eax=0x{:08X} ebx=0x{:08X} ecx=0x{:08X}", r.eax, r.ebx, r.ecx);
    if r.ebx != MAGIC {
        println!("[FAIL] ebx != VMXh -- backdoor did not answer");
        std::process::exit(1);
    }
    println!("[OK] backdoor responds (product type ecx=0x{:08X})", r.ecx);

    step(3, "GETSELLENGTH -- host clipboard length");
    println!("(copy some text on the WINDOWS HOST first)");
    let r = call(CMD_GETSELLENGTH, 0);
    println!("all regs: eax=0x{:08X} ebx=0x{:08X} ecx=0x{:08X} edx=0x{:08X}",
             r.eax, r.ebx, r.ecx, r.edx);
    // open-vm-tools returns the length in eax; print candidates to be sure.
    let len = r.eax;
    if len == NO_SELECTION {
        println!("[WARNING] eax=0xFFFFFFFF = no selection. Copy host text, re-run.");
    } else if len == 0 {
        println!("[WARNING] length 0 -- channel answers, host clipboard empty.");
    } else if len > MAX_PIECES * 4 {
        println!("[WARNING] eax=0x{len:08X} implausible as a length; data may be");
        println!("          in another register -- inspect the reg dump above.");
    } else {
        println!("[OK] host clipboard length = {len} bytes -- channel ALIVE");
        step(4, "GETNEXTPIECE -- read the bytes");
        let mut from_eax: Vec<u8> = Vec::new();
        let mut from_ebx: Vec<u8> = Vec::new();
        let pieces = len.div_ceil(4).min(MAX_PIECES);
        for i in 0..pieces {
            let p = call(CMD_GETNEXTPIECE, 0);
            if i < 3 {
                println!("  piece {i}: eax=0x{:08X} ebx=0x{:08X}", p.eax, p.ebx);
            }
            from_eax.extend_from_slice(&p.eax.to_le_bytes());
            from_ebx.extend_from_slice(&p.ebx.to_le_bytes());
        }
        from_eax.truncate(len as usize);
        from_ebx.truncate(len as usize);
        println!("decoded (assuming data in EAX): {:?}",
                 String::from_utf8_lossy(&from_eax));
        println!("decoded (assuming data in EBX): {:?}",
                 String::from_utf8_lossy(&from_ebx));
        println!("[OK] read path exercised -- whichever line shows your host");
        println!("     text tells us the data register for v2");
    }

    if write_test {
        step(5, "SETSELLENGTH + SETSELPIECE -- write host clipboard");
        let payload = b"clipsync backdoor probe OK";
        call(CMD_SETSELLENGTH, payload.len() as u32);
        for chunk in payload.chunks(4) {
            let mut w = [0u8; 4];
            w[..chunk.len()].copy_from_slice(chunk);
            call(CMD_SETSELPIECE, u32::from_le_bytes(w));
        }
        println!("[OK] wrote {} bytes. Now press Ctrl+V on the WINDOWS HOST.",
                 payload.len());
        println!("     Expect: clipsync backdoor probe OK");
        println!("     Nothing pastes -> write path dead / needs a different reg.");
    } else {
        println!("\n(re-run with --write to test guest->host)");
    }

    println!("\n=== done. paste the whole output back. ===");
}
