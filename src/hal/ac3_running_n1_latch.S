.syntax unified
.thumb
.text
.align 2
.thumb_set baseline_hook, 0x6dd01
.thumb_set plt_timestamp, 0x6cc90
.thumb_set plt_open, 0x6bff0
.thumb_set plt_read, 0x6bfc0
.thumb_set plt_close, 0x6bfe0
.thumb_set plt_strstr, 0x6aef0
.thumb_set plt_strtoul, 0x6b050
.thumb_set plt_write, 0x6c030
/* Called under the existing device/stream locks before a direct write.
 * Keep the verified TrueHD behavior. For AC3, wait for tinyalsa's actual
 * RUNNING/DRAINING status, then re-latch the existing HDMI N1 value once.
 * +0x156 is verified padding between standby(+0x154) and dev(+0x158).
 * No FIFO reset, timing threshold, sleep, or stream recreation.
 */
.global ac3_running_n1_latch
.type ac3_running_n1_latch,%function
.thumb_func
ac3_running_n1_latch:
    push {r4-r7,lr}
    sub sp,#4
    mov r4,r10
    bl baseline_hook
    cmp r0,#0
    beq active
    movs r0,#0
    strb.w r0,[r4,#0x156]
    b done
active:
    ldr.w r0,[r4,#0x1f8]
    lsrs r0,r0,#24
    cmp r0,#9
    bne done
    ldrb.w r0,[r4,#0x156]
    cmp r0,#0
    bne done
    ldr.w r0,[r4,#0x144]
    cmp r0,#0
    beq done
    sub.w sp,sp,#4096
    sub sp,#64
    add r1,sp,#16
    add r2,sp,#24
    blx plt_timestamp
    cmp r0,#0
    blt release
    adr r0,regs_path
    movs r1,#0
    blx plt_open
    cmp r0,#0
    blt release
    mov r5,r0
    add r1,sp,#64
    movw r2,#4095
    blx plt_read
    mov r6,r0
    mov r0,r5
    blx plt_close
    cmp r6,#0
    ble release
    add r1,sp,#64
    movs r0,#0
    strb r0,[r1,r6]
    add r0,sp,#64
    adr r1,needle
    blx plt_strstr
    cmp r0,#0
    beq release
    adds r0,#14
    movs r1,#0
    movs r2,#16
    blx plt_strtoul
    cmp r0,#255
    bhi release
    mov r5,r0
    adr r7,command
    ldm r7,{r0-r3}
    mov r6,sp
    stm r6,{r0-r3}
    adr r7,hex_digits
    and r0,r5,#15
    ldrb r0,[r7,r0]
    strb r0,[r6,#12]
    lsrs r0,r5,#4
    ldrb r0,[r7,r0]
    strb r0,[r6,#11]
    adr r0,debug_path
    movs r1,#1
    blx plt_open
    cmp r0,#0
    blt release
    mov r5,r0
    mov r1,sp
    movs r2,#13
    blx plt_write
    mov r6,r0
    mov r0,r5
    blx plt_close
    cmp r6,#13
    bne release
    movs r0,#1
    strb.w r0,[r4,#0x156]
release:
    add sp,#64
    add.w sp,sp,#4096
done:
    ldrb.w r0,[r10,#0x154]
    add sp,#4
    pop {r4-r7,pc}
.size ac3_running_n1_latch,.-ac3_running_n1_latch
.balign 4
command:
    .asciz "wh10003200,00"
    .balign 4
regs_path:
    .asciz "/sys/class/amhdmitx/amhdmitx0/dump_debug_reg"
debug_path:
    .asciz "/sys/class/amhdmitx/amhdmitx0/debug"
needle:
    .asciz "[0x10003200]0x"
hex_digits:
    .ascii "0123456789abcdef"
