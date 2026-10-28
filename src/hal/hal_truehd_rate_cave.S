.syntax unified
.thumb
.global _start
_start:
    /* The original DTS-HD wrapper upgrades mixer format 3 to 8 and sets
       the HBR ALSA carrier to 192 kHz. TrueHD uses mixer format 7 and
       needs the same carrier without changing its format. */
    cmp     r1, #3
    bne     check_truehd
    movs    r1, #8
    b       set_rate
check_truehd:
    cmp     r1, #7
    bne     original_prologue
set_rate:
    movw    r3, #0xee00
    movt    r3, #2
    str.w   r3, [r2, #0xfc]
original_prologue:
    push.w  {r4, r5, r6, r7, r8, r9, lr}
