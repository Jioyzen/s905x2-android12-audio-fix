.syntax unified
.thumb
.text
.align 2
.global dtses_format_guard
.thumb_func
dtses_format_guard:
    cmp r1,#3
    bne existing_hd
    ldr.w r3,[r2,#0x124]
    movw r12,#0x13f
    cmp r3,r12
    bne existing_hd
    /* The captured DTS-ES 6.1 stream is core DTS: retain type 3,
       use the requested base sample rate, and replay the stock prologue. */
    ldr.w r3,[r2,#0x12c]
    str.w r3,[r2,#0xfc]
    push.w {r4-r9,lr}
    b.w 0x5b808
existing_hd:
    b.w 0x6d9c0
.balign 4
.global dts_base_position_guard
.thumb_func
dts_base_position_guard:
    /* Only apply the HD position factor to a serialized HBR rate.
       Core DTS at its base ALSA rate follows the original position path. */
    ldr.w r0,[r4,#0xfc]
    ldr.w r1,[r4,#0x12c]
    cmp r0,r1
    beq core_position
    ldr.w r0,[r4,#0x1f8]
    b.w 0x6da84
core_position:
    b.w 0x6daa0
