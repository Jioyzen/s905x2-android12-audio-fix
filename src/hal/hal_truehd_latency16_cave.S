.syntax unified
.thumb
.global _start
_start:
    /* out_get_latency_frames: TrueHD HBR consumes ALSA frames at 4x
       the 192 kHz nominal rate. Convert DMA delay to 48 kHz content
       frames using /16. The other formats return to the original check. */
    cmp.w   r0, #0xe000000
    bne     other_format
    movs    r7, #16
    nop
    nop
other_format:
    nop
    nop
