#pragma once
#include <stdint.h>
typedef uint32_t audio_format_t;
typedef uint32_t audio_channel_mask_t;
enum {
    AUDIO_FORMAT_INVALID      = 0xFFFFFFFFu,
    AUDIO_FORMAT_DEFAULT      = 0,
    AUDIO_FORMAT_PCM_16_BIT   = 0x1u,
    AUDIO_FORMAT_AC3          = 0x09000000u,
    AUDIO_FORMAT_E_AC3        = 0x0A000000u,
    AUDIO_FORMAT_DTS          = 0x0B000000u,
    AUDIO_FORMAT_DTS_HD       = 0x0C000000u,
    AUDIO_FORMAT_DOLBY_TRUEHD = 0x0E000000u,
    AUDIO_FORMAT_E_AC3_JOC    = 0x0F000000u,
    AUDIO_FORMAT_IEC61937     = 0x23000000u,
};
