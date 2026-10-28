.syntax unified
.thumb
.text
.align 2

.thumb_set stock_get_total, 0x6b8b0
.thumb_set stock_standby, 0x4141d

/* Called from out_write_direct with the device and stream locks held.
 * Once the first MAT burst has passed through the encoder, rebuild the PCM
 * output on the next write. Byte 0x155 is padding after the standby flag;
 * calloc initializes it to zero for each newly opened stream.
 */
.global truehd_post_first_burst
.type truehd_post_first_burst,%function
.thumb_func
truehd_post_first_burst:
    push {r4, lr}
    mov r4, r10
    ldrb.w r0, [r4, #0x154]
    cbnz r0, 1f
    ldrb.w r0, [r4, #0x155]
    cbnz r0, 1f
    ldr.w r0, [r4, #0x1f8]
    lsrs r0, r0, #24
    cmp r0, #14
    bne 1f
    blx stock_get_total
    cmp r1, #0
    bne 2f
    ldr.w r1, =61440
    cmp r0, r1
    blo 1f
2:
    movs r0, #1
    strb.w r0, [r4, #0x155]
    mov r0, r4
    bl stock_standby
1:
    ldrb.w r0, [r4, #0x154]
    pop {r4, pc}
.size truehd_post_first_burst,.-truehd_post_first_burst
