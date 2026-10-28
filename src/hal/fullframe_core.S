.syntax unified
.thumb
.text
.align 2
.thumb_set previous_hook, 0x6dd91
.thumb_set stock_standby, 0x4141d
.global fullframe_core_probe
.thumb_func
fullframe_core_probe:
    push {r4,r6,r7,lr}
    ldr.w r0,[r10,#0x1f8]
    cmp.w r0,#0x0b000000
    bne done
    ldrb.w r0,[r10,#0x157]
    cmp r0,#0
    bne done
    movw r0,#2052
    cmp r5,r0
    blo done
    ldr r6,[sp,#0x54] /* original out_write_direct buffer at caller sp+0x44 */
    cmp r6,#0
    beq done
    ldr r0,[r6]
    movw r7,#0xfe7f
    movt r7,#0x0180
    cmp r0,r7
    bne done
    ldr r0,[r6,#4]
    rev r0,r0
    ubfx r1,r0,#18,#7
    cmp r1,#15 /* 512 PCM samples */
    bne done
    ubfx r1,r0,#4,#14
    movw r2,#2047 /* 2048 byte compressed frame */
    cmp r1,r2
    bne done
    ldr.w r0,[r6,#2048]
    cmp r0,r7 /* require next core sync; EXSS is deliberately excluded */
    bne done
    ldr.w r0,[r10,#0x12c]
    movw r1,#48000
    cmp r0,r1
    bne done
    movs r0,#1
    strb.w r0,[r10,#0x157]
    ldrb.w r0,[r10,#0x154]
    cmp r0,#0
    bne done
    /* Reopen only before the encoder write, while the original locks are held. */
    mov r0,r10
    bl stock_standby
done:
    bl previous_hook
    pop {r4,r6,r7,pc}
