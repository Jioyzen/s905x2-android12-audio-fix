.syntax unified
.thumb
.text
.align 2
.global native_dtshd_rate
.thumb_func
native_dtshd_rate:
    /* ExoPlayer requests AUDIO_FORMAT_DTS_HD, not IJK's DTS alias.
       Existing mixer type 8 stays type 8; serialize HBR at 192 kHz. */
    cmp r1,#8
    bne existing_formats
    ldr.w r3,[r2,#0x1f8]
    cmp.w r3,#0x0c000000
    bne existing_formats
    movw r3,#0xee00
    movt r3,#2
    str.w r3,[r2,#0xfc]
    push.w {r4-r9,lr}
    b.w 0x5b808
existing_formats:
    b.w 0x6d9c0
