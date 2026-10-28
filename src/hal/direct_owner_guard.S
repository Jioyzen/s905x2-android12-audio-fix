.syntax unified
.thumb
.text
.align 2

.thumb_set close_continue, 0x3c768

/* adev_close_output_stream_new: preserve the active_outputs slot if a newer
 * stream of the same usecase has replaced the stream being closed.
 * r0=usecase, r1=active_outputs offset, r2=0, r4=closing stream, r5=adev.
 */
.global direct_owner_guard
.type direct_owner_guard,%function
.thumb_func
direct_owner_guard:
    add.w r0, r5, r0, lsl #2
    ldr r3, [r0, r1]
    cmp r3, r4
    it eq
    streq r2, [r0, r1]
    b.w close_continue
.size direct_owner_guard,.-direct_owner_guard
