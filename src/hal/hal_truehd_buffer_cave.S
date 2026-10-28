.syntax unified
.thumb
.global _start
_start:
    /* DTS-HD retains its tested format/rate behavior. */
    cmp     r1, #3
    bne     check_truehd
    movs    r1, #8
    b       set_rate
check_truehd:
    cmp     r1, #7
    bne     original_prologue
    /* The live pcm_config at stream+0xf8 has period_size=8192,
       period_count=4 and start_threshold=32768. Increase only TrueHD
       to 8 periods and start after the full 65536-frame queue is primed. */
    movs    r3, #8
    str.w   r3, [r2, #0x104]
    movw    r3, #0
    movt    r3, #1
    str.w   r3, [r2, #0x10c]
set_rate:
    movw    r3, #0xee00
    movt    r3, #2
    str.w   r3, [r2, #0xfc]
original_prologue:
    push.w  {r4, r5, r6, r7, r8, r9, lr}
