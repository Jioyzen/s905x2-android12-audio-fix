/* GCC mangles typedef'd parameters by their typedef name (audio_format_t),
   Clang canonicalises to the underlying type (j). libamaudioutils.so was built
   with GCC, so provide the GCC-style names as tail-branch aliases. */
    .syntax unified
    .thumb
    .global _ZN7android12SPDIFEncoderC2E14audio_format_t
    .type   _ZN7android12SPDIFEncoderC2E14audio_format_t, %function
_ZN7android12SPDIFEncoderC2E14audio_format_t:
    b       _ZN7android12SPDIFEncoderC2Ej

    .global _ZN7android12SPDIFEncoder17isFormatSupportedE14audio_format_t
    .type   _ZN7android12SPDIFEncoder17isFormatSupportedE14audio_format_t, %function
_ZN7android12SPDIFEncoder17isFormatSupportedE14audio_format_t:
    b       _ZN7android12SPDIFEncoder17isFormatSupportedEj

    .global _ZN7android15AC3FrameScannerC2E14audio_format_t
    .type   _ZN7android15AC3FrameScannerC2E14audio_format_t, %function
_ZN7android15AC3FrameScannerC2E14audio_format_t:
    b       _ZN7android15AC3FrameScannerC2Ej
