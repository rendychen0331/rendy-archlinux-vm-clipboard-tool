# Low-bandwidth VMware backdoor IN call.
# Adapted from lucab/vmw_backdoor-rs (src/asm/x86_64-linux.s), which is the
# proven register-handling reference: rbx and rbp are LLVM-reserved and the
# hypervisor writes ebp/edi/esi, so every register is loaded from / stored to
# a struct here in standalone asm rather than via inline-asm clobbers (that
# was the segfault cause in the earlier hand-rolled inline version).
#
# System V AMD64: arg1=rdi (input struct), arg2=rsi (output struct).
# Struct layout (repr(C), 7x u32): eax0 ebx4 ecx8 edx12 ebp16 edi20 esi24.

.text
.global _vmw_lb_in
_vmw_lb_in:
  movq %rbx, %r8      # preserve caller rbx
  movq %rbp, %r9      # preserve caller rbp
  movq %rdi, %r10     # input struct ptr
  movq %rsi, %r11     # output struct ptr

  movl 0(%r10),  %eax
  movl 4(%r10),  %ebx
  movl 8(%r10),  %ecx
  movl 12(%r10), %edx
  movl 16(%r10), %ebp
  movl 20(%r10), %edi
  movl 24(%r10), %esi

  inl %dx, %eax       # the backdoor call

  movl %eax, 0(%r11)
  movl %ebx, 4(%r11)
  movl %ecx, 8(%r11)
  movl %edx, 12(%r11)
  movl %ebp, 16(%r11)
  movl %edi, 20(%r11)
  movl %esi, 24(%r11)

  movq %r8, %rbx      # restore rbx
  movq %r9, %rbp      # restore rbp
  xor %rax, %rax
  ret

.section .note.GNU-stack,"",@progbits
