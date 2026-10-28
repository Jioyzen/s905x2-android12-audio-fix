/*
 * Thin Amlogic SPDIFEncoder adapter for FFmpeg's LGPL IEC61937 muxer.
 * The DTS/MLP parsers and all HD burst/MAT construction stay in upstream
 * libavcodec and libavformat. This file deliberately contains no codec-specific
 * frame or burst layout algorithm.
 */
#include "hdpack.h"

#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#define LOG_TAG "cebox_hdpack"
#include <log/log.h>


#include <libavcodec/avcodec.h>
#include <libavcodec/parser.h>
#include <libavformat/avformat.h>
#include <libavformat/avio.h>
#include <libavutil/mem.h>
#include <libavutil/opt.h>

struct HDPacker {
    int format;
    enum AVCodecID codec_id;
    AVCodecParserContext *parser;
    AVCodecContext *codec;
    AVFormatContext *mux;
    AVIOContext *io;
    AVPacket *packet;
    hd_out_cb callback;
    void *callback_ctx;
    size_t emitted;
    size_t frames;
    size_t skipped_exss;
    int failed;
};

static int write_bursts(void *opaque, const uint8_t *buf, int size)
{
    HDPacker *packer = (HDPacker *)opaque;
    if (size > 0) {
        packer->callback(packer->callback_ctx, buf, (size_t)size);
        packer->emitted += (size_t)size;
    }
    return size;
}

static void close_mux(HDPacker *packer)
{
    if (packer->mux) {
        packer->mux->pb = NULL;
        avformat_free_context(packer->mux);
        packer->mux = NULL;
    }
    avio_context_free(&packer->io);
}

static int open_mux(HDPacker *packer)
{
    AVStream *stream;
    uint8_t *io_buffer;
    int rc;

    packer->failed = 0;
    rc = avformat_alloc_output_context2(&packer->mux, NULL, "spdif", NULL);
    if (rc < 0 || !packer->mux)
        goto fail;
    stream = avformat_new_stream(packer->mux, NULL);
    if (!stream)
        goto fail;
    stream->codecpar->codec_type = AVMEDIA_TYPE_AUDIO;
    stream->codecpar->codec_id = packer->codec_id;
    /* The device's RAW AudioTrack opens at 48 kHz. The muxer requires a
     * declared stream rate even though DTS frame cadence is read from each
     * core header and TrueHD MAT timing from each access unit. */
    stream->codecpar->sample_rate = 48000;
    if (packer->format == HDPACK_DTSHD &&
        av_opt_set_int(packer->mux->priv_data, "dtshd_rate", 768000, 0) < 0)
        goto fail;

    io_buffer = av_malloc(8192);
    if (!io_buffer)
        goto fail;
    packer->io = avio_alloc_context(io_buffer, 8192, 1, packer,
                                   NULL, write_bursts, NULL);
    if (!packer->io) {
        av_free(io_buffer);
        goto fail;
    }
    packer->mux->pb = packer->io;
    packer->mux->flags |= AVFMT_FLAG_CUSTOM_IO;
    if (avformat_write_header(packer->mux, NULL) < 0)
        goto fail;

    return 0;
fail:
    close_mux(packer);
    packer->failed = 1;
    return -1;
}

static void close_stream(HDPacker *packer)
{
    av_packet_free(&packer->packet);
    av_parser_close(packer->parser);
    packer->parser = NULL;
    avcodec_free_context(&packer->codec);
    close_mux(packer);
}

static int open_stream(HDPacker *packer)
{
    packer->failed = 0;
    packer->parser = av_parser_init(packer->codec_id);
    if (!packer->parser)
        goto fail;
    packer->codec = avcodec_alloc_context3(NULL);
    if (!packer->codec)
        goto fail;
    packer->codec->codec_type = AVMEDIA_TYPE_AUDIO;
    packer->codec->codec_id = packer->codec_id;
    if (open_mux(packer) < 0)
        goto fail;
    packer->packet = av_packet_alloc();
    if (!packer->packet)
        goto fail;
    return 0;
fail:
    close_stream(packer);
    packer->failed = 1;
    return -1;
}

HDPacker *hd_create(int format, hd_out_cb callback, void *ctx)
{
    HDPacker *packer;
    if ((format != HDPACK_DTSHD && format != HDPACK_TRUEHD) || !callback)
        return NULL;
    packer = calloc(1, sizeof(*packer));
    if (!packer)
        return NULL;
    packer->format = format;
    packer->codec_id = format == HDPACK_DTSHD ? AV_CODEC_ID_DTS : AV_CODEC_ID_TRUEHD;
    packer->callback = callback;
    packer->callback_ctx = ctx;
    if (open_stream(packer) < 0) {
        free(packer);
        return NULL;
    }
    return packer;
}

void hd_destroy(HDPacker *packer)
{
    if (!packer)
        return;
    close_stream(packer);
    free(packer);
}

static int submit_frame(HDPacker *packer, const uint8_t *data, int size)
{
    int rc;
    /* A seek may land in the middle of a DTS-HD access unit.  The DTS parser
     * then emits its orphan EXSS extension before the next core frame, while
     * the IEC61937 muxer requires a core as the start of an access unit. */
    if (packer->format == HDPACK_DTSHD && size >= 4 &&
        data[0] == 0x64 && data[1] == 0x58 &&
        data[2] == 0x20 && data[3] == 0x25) {
        if (packer->skipped_exss++ < 4)
            ALOGI("cebox DTS skipped orphan EXSS after seek: size=%d", size);
        return 0;
    }
    av_packet_unref(packer->packet);
    if (av_new_packet(packer->packet, size) < 0) {
        ALOGE("cebox DTS av_new_packet failed size=%d", size);
        return -1;
    }
    memcpy(packer->packet->data, data, (size_t)size);
    packer->packet->stream_index = 0;
    rc = av_write_frame(packer->mux, packer->packet);
    if (rc < 0 && packer->format == HDPACK_DTSHD)
        ALOGE("cebox DTS av_write_frame failed rc=%d size=%d first=%02x%02x%02x%02x",
              rc, size, data[0], data[1], data[2], data[3]);
    av_packet_unref(packer->packet);
    if (rc < 0)
        return rc;
    packer->frames++;
    avio_flush(packer->io);
    return packer->io->error;
}

size_t hd_write(HDPacker *packer, const uint8_t *buf, size_t size)
{
    size_t before;
    if (!packer || packer->failed || (!buf && size))
        return 0;
    before = packer->emitted;
    while (size) {
        int chunk = size > 65536 ? 65536 : (int)size;
        uint8_t *padded = av_malloc((size_t)chunk + AV_INPUT_BUFFER_PADDING_SIZE);
        int offset = 0;
        if (!padded) {
            packer->failed = 1;
            break;
        }
        memcpy(padded, buf, (size_t)chunk);
        memset(padded + chunk, 0, AV_INPUT_BUFFER_PADDING_SIZE);
        int stalled = 0;
        while (offset < chunk) {
            uint8_t *frame = NULL;
            int frame_size = 0;
            int consumed = av_parser_parse2(packer->parser, packer->codec,
                                            &frame, &frame_size,
                                            padded + offset, chunk - offset,
                                            AV_NOPTS_VALUE, AV_NOPTS_VALUE, 0);
            if (consumed < 0 || (consumed == 0 && frame_size == 0 && ++stalled > 4)) {
                ALOGE("cebox DTS parser stalled: consumed=%d frame=%d offset=%d chunk=%d",
                      consumed, frame_size, offset, chunk);
                av_log(NULL, AV_LOG_ERROR,
                       "cebox HD parser stalled: format=%d consumed=%d frame=%d offset=%d chunk=%d\n",
                       packer->format, consumed, frame_size, offset, chunk);
                packer->failed = 1;
                break;
            }
            if (consumed || frame_size)
                stalled = 0;
            offset += consumed;
            if (frame_size > 0 && submit_frame(packer, frame, frame_size) < 0) {
                ALOGE("cebox DTS submit failed: frame_size=%d consumed=%d offset=%d chunk=%d",
                      frame_size, consumed, offset, chunk);
                av_log(NULL, AV_LOG_ERROR, "cebox HD muxer rejected frame: format=%d size=%d\n",
                       packer->format, frame_size);
                packer->failed = 1;
                break;
            }
        }
        av_free(padded);
        if (packer->failed)
            break;
        buf += chunk;
        size -= (size_t)chunk;
    }
    return packer->emitted - before;
}

void hd_flush(HDPacker *packer)
{
    /* Called by SPDIFEncoder::reset() on seek. Drop any incomplete AU/MAT
     * instead of joining old and new timelines. The muxer has no trailer. */
    if (!packer)
        return;
    close_stream(packer);
    open_stream(packer);
}

int hd_finish(HDPacker *packer)
{
    uint8_t *frame = NULL;
    int frame_size = 0;
    int consumed;
    if (!packer || packer->failed)
        return -1;
    consumed = av_parser_parse2(packer->parser, packer->codec,
                                &frame, &frame_size, NULL, 0,
                                AV_NOPTS_VALUE, AV_NOPTS_VALUE, 0);
    if (consumed < 0 || (frame_size > 0 && submit_frame(packer, frame, frame_size) < 0)) {
        packer->failed = 1;
        return -1;
    }
    return 0;
}

int hd_format(HDPacker *packer)
{
    return packer ? packer->format : 0;
}

int hd_status(HDPacker *packer, size_t *frames, size_t *emitted)
{
    if (!packer)
        return -1;
    if (frames)
        *frames = packer->frames;
    if (emitted)
        *emitted = packer->emitted;
    return packer->failed ? -1 : 0;
}
