.syntax unified
.thumb
.section .text,"ax",%progbits
.global _start
.type _start,%function
_start:
    b.w cave
    .space (0x6da80 - 0x4080a), 0
cave:
    ldr.w   r0, [r4, #0x1f8]
    movw    r1, #0
    movt    r1, #0x0b00
    cmp     r0, r1
    bne     1f
    ldrd    r2, r3, [r8]
    lsrs    r2, r2, #4
    orr.w   r2, r2, r3, lsl #28
    lsrs    r3, r3, #4
    strd    r2, r3, [r8]
1:
    ldr.w   r0, [r9, #0x240]
    movw    r1, #0x080b
    movt    r1, #0x0004
    bx      r1
