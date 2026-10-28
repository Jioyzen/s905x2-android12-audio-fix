/*
 * SPDIFEncoderHD.cpp - AOSP audio_utils/spdif/SPDIFEncoder with working
 * DTS-HD and Dolby TrueHD (MAT) packing added.
 *
 * AC3 / E-AC3 / DTS use AOSP's original code path unchanged (zero regression).
 * DTS_HD and DOLBY_TRUEHD are routed to the packers in hdpack.c, which were
 * verified against ffmpeg's libavformat/spdifenc.c output.
 *
 * ABI notes (see abi_alias.S):
 *   - libamaudioutils.so references only SPDIFEncoder's ctor/dtor/reset/write.
 *   - The object is allocated with sizeof()==0x50 by that library, which owns
 *     offsets >= 0x30; the base class must therefore not grow beyond 0x2c.
 *   - For the HD formats mFramer is unused by AOSP's paths, so it carries our
 *     packer pointer instead of a FrameScanner.
 */
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <new>

#define LOG_TAG "AudioSPDIF"
#include <log/log.h>
#include <audio_utils/spdif/SPDIFEncoder.h>

#include "AC3FrameScanner.h"
#include "DTSFrameScanner.h"

#ifdef CEBOX_DTS_INPUT_CAPTURE
#include <fcntl.h>
#include <unistd.h>
/* Diagnostic build only. Never compiled into the normal shipping library. */
static int gDtsInputFd = -2;
static size_t gDtsInputBytes = 0;
static void captureDtsInput(const void* data, size_t length) {
    if (gDtsInputBytes >= 2 * 1024 * 1024) return;
    if (gDtsInputFd == -2) {
        gDtsInputFd = open("/data/audio_out/flyniu_dts_input.bin",
                           O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    }
    if (gDtsInputFd < 0) return;
    if (length > 2 * 1024 * 1024 - gDtsInputBytes)
        length = 2 * 1024 * 1024 - gDtsInputBytes;
    ssize_t written = ::write(gDtsInputFd, data, length);
    if (written > 0) gDtsInputBytes += (size_t)written;
}
#endif

#ifdef CEBOX_TRUEHD_INPUT_CAPTURE
#include <fcntl.h>
#include <unistd.h>
/* Diagnostic build only: capture the raw TrueHD access units entering the
 * HAL packer so seek-time input can be decoded independently. */
static int gTruehdInputFd = -2;
static size_t gTruehdInputBytes = 0;
static void captureTrueHDInput(const void* data, size_t length) {
    if (gTruehdInputBytes >= 64 * 1024 * 1024) return;
    if (gTruehdInputFd == -2) {
        gTruehdInputFd = open("/data/audio_out/truehd_input.bin",
                              O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    }
    if (gTruehdInputFd < 0) return;
    if (length > 64 * 1024 * 1024 - gTruehdInputBytes)
        length = 64 * 1024 * 1024 - gTruehdInputBytes;
    ssize_t written = ::write(gTruehdInputFd, data, length);
    if (written > 0) gTruehdInputBytes += (size_t)written;
}
static void captureTrueHDReset(void) {
    static const char marker[] = "CEBOX_TRUEHD_RESET\n";
    if (gTruehdInputFd >= 0)
        ::write(gTruehdInputFd, marker, sizeof(marker) - 1);
}
#endif
#include "hdpack.h"

namespace android {

/* The SEI500 HAL labels some complete DTS-HD MA elementary streams as DTS.
 * Delay only the first DTS frame long enough to inspect the boundary after
 * its core. The actual HD frame parsing/packing remains in upstream FFmpeg. */
static const size_t kDtsProbeMax = 65536;
static const size_t kDtsAutoSentinel = 1;
struct DtsAutoProbe {
    size_t used;
    uint8_t data[kDtsProbeMax];
};

enum DtsProbeResult { DTS_WAIT, DTS_CORE, DTS_HD };

static DtsProbeResult probeDts(const DtsAutoProbe* p)
{
    static const uint8_t coreSync[4] = { 0x7f, 0xfe, 0x80, 0x01 };
    static const uint8_t exssSync[4] = { 0x64, 0x58, 0x20, 0x25 };
    for (size_t off = 0; off + 10 <= p->used; ++off) {
        if (memcmp(p->data + off, coreSync, 4))
            continue;
        size_t coreSize = ((((size_t)p->data[off + 5] << 16) |
                            ((size_t)p->data[off + 6] << 8) |
                            p->data[off + 7]) >> 4 & 0x3fff) + 1;
        if (coreSize < 96 || coreSize > 16384)
            continue;
        if (off + coreSize + 4 > p->used)
            return DTS_WAIT;
        return memcmp(p->data + off + coreSize, exssSync, 4) == 0
                ? DTS_HD : DTS_CORE;
    }
    return DTS_WAIT;
}

const uint16_t SPDIFEncoder::kSPDIFSync1 = 0xF872; // Pa
const uint16_t SPDIFEncoder::kSPDIFSync2 = 0x4E1F; // Pb

static int32_t sEndianDetector = 1;
#define isLittleEndian()  (*((uint8_t *)&sEndianDetector))

static int hdFormatToPacker(audio_format_t format)
{
    return (format == AUDIO_FORMAT_DTS_HD) ? HDPACK_DTSHD : HDPACK_TRUEHD;
}

/* Trampoline: the packer hands every finished burst to writeOutput(). */
static void hdBurstOut(void* ctx, const uint8_t* burst, size_t len)
{
    SPDIFEncoder* self = (SPDIFEncoder*)ctx;
    self->writeOutput(burst, len);
}

SPDIFEncoder::SPDIFEncoder(audio_format_t format)
  : mFramer(NULL)
  , mSampleRate(48000)
  , mBurstBuffer(NULL)
  , mBurstBufferSizeBytes(0)
  , mRateMultiplier(1)
  , mBurstFrames(0)
  , mByteCursor(0)
  , mBitstreamNumber(0)
  , mPayloadBytesPending(0)
  , mScanning(true)
{
    if (format == AUDIO_FORMAT_DTS_HD || format == AUDIO_FORMAT_DOLBY_TRUEHD) {
        /* FFmpeg chooses DTS-HD burst period from each frame's sample rate. */
        mBurstBufferSizeBytes = (format == AUDIO_FORMAT_DTS_HD)
                ? 32768 : 61440;
        mBurstBuffer = NULL;          /* not used by the HD paths */
        mFramer = (FrameScanner*)hd_create(hdFormatToPacker(format),
                                           hdBurstOut, this);
        LOG_ALWAYS_FATAL_IF(mFramer == NULL, "SPDIFEncoder: cannot create HD packer");
        return;
    }

    if (format == AUDIO_FORMAT_DTS) {
        DtsAutoProbe* probe = (DtsAutoProbe*)calloc(1, sizeof(DtsAutoProbe));
        LOG_ALWAYS_FATAL_IF(probe == NULL, "SPDIFEncoder: cannot allocate DTS probe");
        mFramer = (FrameScanner*)probe;
        mBurstBufferSizeBytes = kDtsAutoSentinel;
        return;
    }

    switch(format) {
        case AUDIO_FORMAT_AC3:
        case AUDIO_FORMAT_E_AC3:
        case AUDIO_FORMAT_E_AC3_JOC:
            mFramer = (FrameScanner*)malloc(sizeof(AC3FrameScanner));
            new (mFramer) AC3FrameScanner(format);
            break;
        default:
            break;
    }

    // This a programmer error. Call isFormatSupported() first.
    LOG_ALWAYS_FATAL_IF((mFramer == NULL),
        "SPDIFEncoder: invalid audio format = 0x%08X", format);

    mBurstBufferSizeBytes = sizeof(uint16_t)
            * SPDIF_ENCODED_CHANNEL_COUNT
            * mFramer->getMaxSampleFramesPerSyncFrame();

    ALOGI("SPDIFEncoder: mBurstBufferSizeBytes = %zu, littleEndian = %d",
            mBurstBufferSizeBytes, isLittleEndian());
    mBurstBuffer = (uint16_t*)malloc(mBurstBufferSizeBytes);
    clearBurstBuffer();
}

SPDIFEncoder::SPDIFEncoder()
    : SPDIFEncoder(AUDIO_FORMAT_AC3)
{
}

SPDIFEncoder::~SPDIFEncoder()
{
    free(mBurstBuffer);
    if (mFramer != NULL) {
        /* HD formats keep a HDPacker in the mFramer slot */
        if (mBurstBuffer == NULL) {
            if (mBurstBufferSizeBytes == kDtsAutoSentinel)
                free(mFramer);
            else
                hd_destroy((HDPacker*)mFramer);
        } else {
            mFramer->~FrameScanner();
            free(mFramer);
        }
    }
}

bool SPDIFEncoder::isFormatSupported(audio_format_t format)
{
    switch(format) {
        case AUDIO_FORMAT_AC3:
        case AUDIO_FORMAT_E_AC3:
        case AUDIO_FORMAT_E_AC3_JOC:
        case AUDIO_FORMAT_DTS:
        case AUDIO_FORMAT_DTS_HD:
        case AUDIO_FORMAT_DOLBY_TRUEHD:
            return true;
        default:
            return false;
    }
}

int SPDIFEncoder::getBytesPerOutputFrame()
{
    return SPDIF_ENCODED_CHANNEL_COUNT * sizeof(int16_t);
}

bool SPDIFEncoder::wouldOverflowBuffer(size_t numBytes) const {
    return (numBytes > mBurstBufferSizeBytes)
        || (mByteCursor > (mBurstBufferSizeBytes - numBytes));
}

void SPDIFEncoder::writeBurstBufferShorts(const uint16_t *buffer, size_t numShorts)
{
    LOG_ALWAYS_FATAL_IF((mBurstBuffer == NULL), "mBurstBuffer never allocated");
    mByteCursor = (mByteCursor + 1) & ~1;
    size_t bytesToWrite = numShorts * sizeof(uint16_t);
    if (wouldOverflowBuffer(bytesToWrite)) {
        ALOGE("SPDIFEncoder::%s() Burst buffer overflow!", __func__);
        reset();
        return;
    }
    memcpy(&mBurstBuffer[mByteCursor >> 1], buffer, bytesToWrite);
    mByteCursor += bytesToWrite;
}

void SPDIFEncoder::writeBurstBufferBytes(const uint8_t *buffer, size_t numBytes)
{
    if (wouldOverflowBuffer(numBytes)) {
        ALOGE("SPDIFEncoder::%s() Burst buffer overflow!", __func__);
        clearBurstBuffer();
        return;
    }
    if (numBytes == 0) {
        return;
    }
    uint16_t pad = mBurstBuffer[mByteCursor >> 1];
    for (size_t i = 0; i < numBytes; i++) {
        if (mByteCursor & 1 ) {
            pad |= *buffer++;
            mBurstBuffer[mByteCursor >> 1] = pad;
            pad = 0;
        } else {
            pad |= (*buffer++) << 8;
        }
        mByteCursor++;
    }
    if (mByteCursor & 1 ){
        mBurstBuffer[mByteCursor >> 1] = pad;
    }
}

void SPDIFEncoder::sendZeroPad()
{
    size_t burstSize = mFramer->getSampleFramesPerSyncFrame() * sizeof(uint16_t)
            * SPDIF_ENCODED_CHANNEL_COUNT;
    if (mByteCursor > burstSize) {
        ALOGE("SPDIFEncoder: Burst buffer, contents too large!");
        clearBurstBuffer();
    } else {
        mByteCursor = burstSize;
    }
}

void SPDIFEncoder::reset()
{
    ALOGV("SPDIFEncoder: reset()");
#ifdef CEBOX_TRUEHD_INPUT_CAPTURE
    if (mBurstBuffer == NULL && mBurstBufferSizeBytes == 61440)
        captureTrueHDReset();
#endif
    /* HD formats carry a HDPacker in the mFramer slot: flush the tail burst. */
    if (mBurstBuffer == NULL) {
        if (mBurstBufferSizeBytes == kDtsAutoSentinel)
            ((DtsAutoProbe*)mFramer)->used = 0;
        else if (mFramer != NULL) {
            /* Temporary device-side seek diagnostic.  This branch is used
             * only by the FFmpeg HD packers, never AC3/E-AC3/DTS. */
            ALOGI("cebox HD SPDIFEncoder reset: framer=%p", mFramer);
            hd_flush((HDPacker*)mFramer);
        }
        return;
    }
    clearBurstBuffer();
    if (mFramer != NULL) {
        mFramer->resetBurst();
    }
    mPayloadBytesPending = 0;
    mScanning = true;
}

/* Match the upstream FFmpeg spdif muxer's DTS-in-WAV/CD case. A core
 * frame exactly fills its carrier period, leaving no room for an IEC header.
 * Do not grow the period or truncate the compressed frame. */
static bool isFullPeriodDtsCore(const FrameScanner* framer)
{
    const int type = framer->getDataType();
    return type >= 11 && type <= 13 &&
            framer->getFrameSizeBytes() ==
                framer->getSampleFramesPerSyncFrame() * sizeof(uint16_t) *
                SPDIF_ENCODED_CHANNEL_COUNT;
}

void SPDIFEncoder::flushBurstBuffer()
{
    const int preambleSize = 4 * sizeof(uint16_t);
    if (mByteCursor > preambleSize) {
        uint16_t numBytes = (mByteCursor - preambleSize);
        if (!isFullPeriodDtsCore(mFramer))
            mBurstBuffer[3] = mFramer->convertBytesToLengthCode(numBytes);
        sendZeroPad();
        writeOutput(mBurstBuffer, mByteCursor);
    }
    reset();
}

void SPDIFEncoder::clearBurstBuffer()
{
    if (mBurstBuffer) {
        memset(mBurstBuffer, 0, mBurstBufferSizeBytes);
    }
    mByteCursor = 0;
}

void SPDIFEncoder::startDataBurst()
{
    uint16_t preamble[4];
    uint16_t burstInfo = (mBitstreamNumber << 13)
        | (mFramer->getDataTypeInfo() << 8)
        | mFramer->getDataType();

    mRateMultiplier = mFramer->getRateMultiplier();

    preamble[0] = kSPDIFSync1;
    preamble[1] = kSPDIFSync2;
    preamble[2] = burstInfo;
    preamble[3] = 0;
    if (!isFullPeriodDtsCore(mFramer))
        writeBurstBufferShorts(preamble, 4);
}

size_t SPDIFEncoder::startSyncFrame()
{
    size_t headerSize = mFramer->getHeaderSizeBytes();
    writeBurstBufferBytes(mFramer->getHeaderAddress(), headerSize);
    size_t frameSize = mFramer->getFrameSizeBytes();
    if (frameSize < headerSize) {
        ALOGE("SPDIFEncoder: invalid frameSize = %zu", frameSize);
        return 0;
    }
    return frameSize - headerSize;
}

ssize_t SPDIFEncoder::write( const void* buffer, size_t numBytes )
{
#ifdef CEBOX_TRUEHD_INPUT_CAPTURE
    if (mBurstBuffer == NULL && mBurstBufferSizeBytes == 61440)
        captureTrueHDInput(buffer, numBytes);
#endif
#ifdef CEBOX_DTS_INPUT_CAPTURE
    if (mBurstBuffer != NULL && mFramer != NULL &&
        mFramer->getDataType() >= 11 && mFramer->getDataType() <= 13)
        captureDtsInput(buffer, numBytes);
#endif
    if (mBurstBuffer == NULL && mBurstBufferSizeBytes == kDtsAutoSentinel) {
        DtsAutoProbe* probe = (DtsAutoProbe*)mFramer;
        const uint8_t* incoming = (const uint8_t*)buffer;
        size_t left = numBytes;
        while (left) {
            size_t room = kDtsProbeMax - probe->used;
            size_t take = left < room ? left : room;
            memcpy(probe->data + probe->used, incoming, take);
            probe->used += take;
            incoming += take;
            left -= take;
            DtsProbeResult result = probeDts(probe);
            if (result == DTS_WAIT && probe->used < kDtsProbeMax)
                continue;
            if (result == DTS_WAIT)
                result = DTS_CORE; /* bounded fallback preserves ordinary DTS */

            const size_t pending = probe->used;
            if (result == DTS_HD) {
                HDPacker* packer = hd_create(HDPACK_DTSHD, hdBurstOut, this);
                LOG_ALWAYS_FATAL_IF(packer == NULL, "SPDIFEncoder: cannot create DTS-HD packer");
                mFramer = (FrameScanner*)packer;
                mBurstBufferSizeBytes = 32768;
                ALOGI("SPDIFEncoder: DTS-labeled stream contains EXSS; using FFmpeg DTS-HD IEC packer");
            } else {
                mFramer = (FrameScanner*)malloc(sizeof(DTSFrameScanner));
                LOG_ALWAYS_FATAL_IF(mFramer == NULL, "SPDIFEncoder: cannot create DTS scanner");
                new (mFramer) DTSFrameScanner();
                mBurstBufferSizeBytes = sizeof(uint16_t) * SPDIF_ENCODED_CHANNEL_COUNT
                        * mFramer->getMaxSampleFramesPerSyncFrame();
                mBurstBuffer = (uint16_t*)malloc(mBurstBufferSizeBytes);
                LOG_ALWAYS_FATAL_IF(mBurstBuffer == NULL, "SPDIFEncoder: cannot allocate DTS burst");
                clearBurstBuffer();
            }
            write(probe->data, pending);
            free(probe);
            if (left)
                write(incoming, left);
            return numBytes;
        }
        return numBytes;
    }
    /* HD formats: hand the payload to the dedicated packer, which emits
     * complete IEC61937 bursts through writeOutput(). */
    if (mBurstBuffer == NULL) {            /* HD format: packer in mFramer */
        if (mFramer != NULL && numBytes > 0) {
            hd_write((HDPacker*)mFramer, (const uint8_t*)buffer, numBytes);
        }
        return numBytes;
    }

    const uint8_t* data = (const uint8_t*) buffer;
    size_t bytesLeft = numBytes;

    while (bytesLeft > 0) {
        if (mScanning) {
            // Scan the next byte for a sync word.
            if (mFramer->scan(*data)) {
                // Found a sync word. Start a new burst if needed.
                if (mFramer->isFirstInBurst()) {
                    if (mByteCursor != 0)
                        flushBurstBuffer();
                    startDataBurst();
                } else if (mByteCursor == 0) {
                    /* The first E-AC3 burst needs a preamble, but there is
                     * nothing to flush and resetBurst() must not consume its
                     * first six-block frame. */
                    startDataBurst();
                }
                mPayloadBytesPending = startSyncFrame();
                mScanning = false;
            }
            data++;
            bytesLeft--;
        } else {
            size_t bytesToWrite = bytesLeft;
            if (bytesToWrite > mPayloadBytesPending) {
                bytesToWrite = mPayloadBytesPending;
            }
            writeBurstBufferBytes(data, bytesToWrite);
            data += bytesToWrite;
            bytesLeft -= bytesToWrite;
            mPayloadBytesPending -= bytesToWrite;
            if (mPayloadBytesPending == 0) {
                if (mFramer->isLastInBurst()) {
                    flushBurstBuffer();
                }
                mScanning = true;
            }
        }
    }
    return numBytes;
}

}  // namespace android
