.syntax unified
.thumb
.text
.align 2
.global fullframe_format_guard
.thumb_func
fullframe_format_guard:
    cmp r1,#3
    bne previous
    ldrb.w r3,[r2,#0x157]
    cmp r3,#1
    bne previous
    ldr.w r3,[r2,#0x12c]
    str.w r3,[r2,#0xfc]
    push.w {r4-r9,lr}
    b.w 0x5b808
previous:
    b.w 0x6db30
