#define LOG_TAG "SystemSurroundDecoder"
#include <media/stagefright/omx/SimpleSoftOMXComponent.h>
#include <media/hardware/OMXPluginBase.h>
#include <OMX_AudioExt.h>
#include <OMX_IndexExt.h>
#include <dlfcn.h>
#include <algorithm>
#include <deque>
#include <vector>
#include <cstring>
#include <cstdint>
#include <cstdarg>
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavutil/channel_layout.h>
#include <libavutil/mathematics.h>
#include <libswresample/swresample.h>
}

// New NDK headers use this abort helper; the Android 12 platform libc++
// predates it. Containers stay private to this library and use global new/delete.
namespace std { inline namespace __ndk1 {
__attribute__((noreturn)) void __libcpp_verbose_abort(const char *fmt, ...) {
    va_list args; va_start(args, fmt); __android_log_vprint(ANDROID_LOG_FATAL, LOG_TAG, fmt, args); va_end(args); abort();
}
} }

namespace android {
struct CodecSpec { const char *name, *mime, *role; AVCodecID id; OMX_AUDIO_CODINGTYPE coding; };
static const CodecSpec specs[] = {
    {"OMX.google.ffsurround.ac3.decoder", "audio/ac3", "audio_decoder.ac3", AV_CODEC_ID_AC3, (OMX_AUDIO_CODINGTYPE)OMX_AUDIO_CodingAndroidAC3},
    {"OMX.google.ffsurround.eac3.decoder", "audio/eac3", "audio_decoder.eac3", AV_CODEC_ID_EAC3, (OMX_AUDIO_CODINGTYPE)OMX_AUDIO_CodingAndroidEAC3},
    {"OMX.google.ffsurround.dts.decoder", "audio/vnd.dts", "audio_decoder.dts", AV_CODEC_ID_DTS, (OMX_AUDIO_CODINGTYPE)0x7f000000},
    {"OMX.google.ffsurround.dtshd.decoder", "audio/vnd.dts.hd", "audio_decoder.dtshd", AV_CODEC_ID_DTS, (OMX_AUDIO_CODINGTYPE)0x7f000000},
    {"OMX.google.ffsurround.dtse.decoder", "audio/vnd.dts.hd;profile=lbr", "audio_decoder.dtse", AV_CODEC_ID_DTS, (OMX_AUDIO_CODINGTYPE)0x7f000000},
    {"OMX.google.ffsurround.truehd.decoder", "audio/true-hd", "audio_decoder.truehd", AV_CODEC_ID_TRUEHD, (OMX_AUDIO_CODINGTYPE)0x7f000002},
};
static const CodecSpec *findSpec(const char *name) {
    for (const auto &s : specs) if (!strcmp(name, s.name)) return &s;
    // Existing app processes can retain the old MediaCodec names in a cache.
    // Serve those audio-only aliases through the same replacement decoder.
    static const char *aliases[] = {"OMX.amlogic.audio.decoder.ac3", "OMX.amlogic.audio.decoder.eac3",
        "OMX.amlogic.audio.decoder.dts", "OMX.amlogic.audio.decoder.dtshd", "OMX.amlogic.audio.decoder.dtse"};
    for (size_t i = 0; i < sizeof(aliases) / sizeof(aliases[0]); ++i) if (!strcmp(name, aliases[i])) return &specs[i];
    return nullptr;
}
template<class T> static void initParam(T *p) {
    memset(p, 0, sizeof(*p)); p->nSize = sizeof(*p); p->nVersion.s.nVersionMajor = 1;
}
static OMX_AUDIO_CHANNELTYPE channelType(AVChannel c) {
    switch (c) {
        case AV_CHAN_FRONT_LEFT: return OMX_AUDIO_ChannelLF;
        case AV_CHAN_FRONT_RIGHT: return OMX_AUDIO_ChannelRF;
        case AV_CHAN_FRONT_CENTER: return OMX_AUDIO_ChannelCF;
        case AV_CHAN_LOW_FREQUENCY: return OMX_AUDIO_ChannelLFE;
        case AV_CHAN_BACK_LEFT: return OMX_AUDIO_ChannelLR;
        case AV_CHAN_BACK_RIGHT: return OMX_AUDIO_ChannelRR;
        case AV_CHAN_SIDE_LEFT: return OMX_AUDIO_ChannelLS;
        case AV_CHAN_SIDE_RIGHT: return OMX_AUDIO_ChannelRS;
        case AV_CHAN_BACK_CENTER: return OMX_AUDIO_ChannelCS;
        default: return OMX_AUDIO_ChannelNone;
    }
}
struct PcmBlock {
    std::vector<uint8_t> data;
    size_t offset = 0;
    int channels = 0, rate = 0;
    OMX_TICKS pts = 0;
    OMX_AUDIO_CHANNELTYPE map[OMX_AUDIO_MAXCHANNELS]{};
};

class SurroundDecoder final : public SimpleSoftOMXComponent {
public:
    SurroundDecoder(const CodecSpec &s, const OMX_CALLBACKTYPE *cb, OMX_PTR app, OMX_COMPONENTTYPE **component)
        : SimpleSoftOMXComponent(s.name, cb, app, component), spec(s) {
        mapping[0] = OMX_AUDIO_ChannelLF; mapping[1] = OMX_AUDIO_ChannelRF;
        for (unsigned port = 0; port < 2; ++port) {
            OMX_PARAM_PORTDEFINITIONTYPE def; initParam(&def);
            def.nPortIndex = port; def.eDir = port ? OMX_DirOutput : OMX_DirInput;
            def.nBufferCountMin = def.nBufferCountActual = 4;
            def.nBufferSize = port ? 65536 : 262144;
            def.bEnabled = OMX_TRUE; def.bPopulated = OMX_FALSE;
            def.eDomain = OMX_PortDomainAudio; def.bBuffersContiguous = OMX_FALSE;
            def.nBufferAlignment = 1;
            def.format.audio.cMIMEType = const_cast<char *>(port ? "audio/raw" : s.mime);
            def.format.audio.eEncoding = port ? OMX_AUDIO_CodingPCM : s.coding;
            addPort(def);
        }
        ALOGI("create %s (FFmpeg %s), PCM software decoder", s.name, av_version_info());
    }
    OMX_ERRORTYPE initCheck() const override { return avcodec_find_decoder(spec.id) ? OMX_ErrorNone : OMX_ErrorComponentNotFound; }
protected:
    ~SurroundDecoder() override { closeDecoder(); }
    OMX_ERRORTYPE internalGetParameter(OMX_INDEXTYPE index, OMX_PTR params) override {
        if (!params) return OMX_ErrorBadParameter;
        if (index == OMX_IndexParamAudioInit) {
            auto *p = static_cast<OMX_PORT_PARAM_TYPE *>(params);
            if (!isValidOMXParam(p)) return OMX_ErrorBadParameter;
            p->nPorts = 2; p->nStartPortNumber = 0; return OMX_ErrorNone;
        }
        if (index == OMX_IndexParamAudioPortFormat) {
            auto *p = static_cast<OMX_AUDIO_PARAM_PORTFORMATTYPE *>(params);
            if (!isValidOMXParam(p) || p->nPortIndex > 1) return OMX_ErrorBadParameter;
            if (p->nIndex) return OMX_ErrorNoMore;
            p->eEncoding = p->nPortIndex ? OMX_AUDIO_CodingPCM : spec.coding; return OMX_ErrorNone;
        }
        if (index == OMX_IndexParamAudioPcm) {
            auto *p = static_cast<OMX_AUDIO_PARAM_PCMMODETYPE *>(params);
            if (!isValidOMXParam(p) || p->nPortIndex != 1) return OMX_ErrorBadParameter;
            p->nChannels = channels; p->eNumData = OMX_NumericalDataSigned;
            p->eEndian = OMX_EndianLittle; p->bInterleaved = OMX_TRUE;
            p->nBitPerSample = 16; p->nSamplingRate = rate; p->ePCMMode = OMX_AUDIO_PCMModeLinear;
            memcpy(p->eChannelMapping, mapping, sizeof(mapping)); return OMX_ErrorNone;
        }
        if (index == OMX_IndexParamStandardComponentRole) {
            auto *p = static_cast<OMX_PARAM_COMPONENTROLETYPE *>(params);
            if (!isValidOMXParam(p)) return OMX_ErrorBadParameter;
            snprintf(reinterpret_cast<char *>(p->cRole), sizeof(p->cRole), "%s", spec.role); return OMX_ErrorNone;
        }
        if ((int)index == OMX_IndexParamAudioAndroidAc3 || (int)index == OMX_IndexParamAudioAndroidEac3) {
            // Both Android compressed-audio structures start with port/channels/rate.
            auto *p = static_cast<OMX_U32 *>(params);
            if (p[0] < 20 || p[2] != 0) return OMX_ErrorBadParameter;
            p[3] = channels; p[4] = rate; return OMX_ErrorNone;
        }
        if ((unsigned)index >= 0x7f100000 && (unsigned)index <= 0x7f100006) {
            auto *p = static_cast<OMX_U32 *>(params);
            if (p[0] < 12 || p[2] != 0) return OMX_ErrorBadParameter;
            if ((unsigned)index == 0x7f100006 && p[0] >= 24) {
                p[3] = OMX_FALSE; p[4] = spec.id == AV_CODEC_ID_EAC3 ? 2 : 1; p[5] = 0;
            } else if (((unsigned)index == 0x7f100000 || (unsigned)index == 0x7f100004) && p[0] >= 40) {
                p[3] = channels; p[4] = rate; p[5] = 16; p[6] = 0; p[7] = 0; p[8] = 1; p[9] = 0;
            }
            return OMX_ErrorNone;
        }
        return SimpleSoftOMXComponent::internalGetParameter(index, params);
    }
    OMX_ERRORTYPE internalSetParameter(OMX_INDEXTYPE index, const OMX_PTR params) override {
        if (!params) return OMX_ErrorBadParameter;
        if (index == OMX_IndexParamStandardComponentRole) {
            auto *p = static_cast<OMX_PARAM_COMPONENTROLETYPE *>(params);
            if (!isValidOMXParam(p) || strncmp(reinterpret_cast<char *>(p->cRole), spec.role, sizeof(p->cRole))) return OMX_ErrorBadParameter;
            return OMX_ErrorNone;
        }
        if (index == OMX_IndexParamAudioPortFormat) {
            auto *p = static_cast<OMX_AUDIO_PARAM_PORTFORMATTYPE *>(params);
            if (!isValidOMXParam(p) || p->nPortIndex > 1) return OMX_ErrorBadParameter;
            return p->eEncoding == (p->nPortIndex ? OMX_AUDIO_CodingPCM : spec.coding) ? OMX_ErrorNone : OMX_ErrorUnsupportedSetting;
        }
        if (index == OMX_IndexParamAudioPcm) {
            auto *p = static_cast<OMX_AUDIO_PARAM_PCMMODETYPE *>(params);
            if (!isValidOMXParam(p) || p->nPortIndex != 1 || p->nBitPerSample != 16) return OMX_ErrorBadParameter;
            return OMX_ErrorNone;
        }
        if ((int)index == OMX_IndexParamAudioAndroidAc3 || (int)index == OMX_IndexParamAudioAndroidEac3) {
            auto *p = static_cast<OMX_U32 *>(params);
            if (p[0] < 20 || p[2] != 0 || p[3] > 8) return OMX_ErrorBadParameter;
            return OMX_ErrorNone;
        }
        if ((unsigned)index >= 0x7f100000 && (unsigned)index <= 0x7f100006) {
            auto *p = static_cast<OMX_U32 *>(params);
            return p[0] >= 12 && p[2] == 0 ? OMX_ErrorNone : OMX_ErrorBadParameter;
        }
        return SimpleSoftOMXComponent::internalSetParameter(index, params);
    }
    OMX_ERRORTYPE getExtensionIndex(const char *name, OMX_INDEXTYPE *index) override {
        if (!name || !index) return OMX_ErrorBadParameter;
        if (strstr(name, "dtshd") || strstr(name, "DTSHD")) { *index = (OMX_INDEXTYPE)0x7f100000; return OMX_ErrorNone; }
        if (strstr(name, "truehd") || strstr(name, "TrueHD")) { *index = (OMX_INDEXTYPE)0x7f100004; return OMX_ErrorNone; }
        if (strstr(name, "dolby") || strstr(name, "Dolby")) { *index = (OMX_INDEXTYPE)0x7f100006; return OMX_ErrorNone; }
        return SoftOMXComponent::getExtensionIndex(name, index);
    }
    void onQueueFilled(OMX_U32) override {
        if (error || changing) return;
        auto &iq = getPortQueue(0); auto &oq = getPortQueue(1);
        while (!oq.empty()) {
            if (!pending.empty()) {
                auto &b = pending.front();
                if (channels != b.channels || rate != b.rate || memcmp(mapping, b.map, sizeof(mapping))) {
                    channels = b.channels; rate = b.rate; memcpy(mapping, b.map, sizeof(mapping));
                    changing = 1;
                    ALOGI("%s output PCM16 %d Hz %d channels", spec.name, rate, channels);
                    notify(OMX_EventPortSettingsChanged, 1, 0, nullptr); return;
                }
                // TrueHD access units can contain just 40 samples (0.83 ms at
                // 48 kHz). Delivering every unit through OMX/Binder separately
                // can starve AudioTrack despite a large client buffer. Gather
                // approximately 20 ms, and always release the tail at EOS.
                if (spec.id == AV_CODEC_ID_TRUEHD && pending.size() == 1 &&
                    b.offset == 0 && b.data.size() < pcmTargetBytes(b) && !eos) {
                    if (iq.empty()) return;
                    BufferInfo *in = *iq.begin(); auto *ih = in->mHeader;
                    bool ok = decodeInput(ih);
                    ih->nFilledLen = 0; in->mOwnedByUs = false;
                    iq.erase(iq.begin()); notifyEmptyBufferDone(ih);
                    if (!ok) { fail(OMX_ErrorStreamCorrupt); return; }
                    continue;
                }
                BufferInfo *out = *oq.begin(); auto *h = out->mHeader;
                size_t count = std::min<size_t>(h->nAllocLen, b.data.size() - b.offset);
                count -= count % (channels * 2);
                if (!count) { fail(OMX_ErrorOverflow); return; }
                memcpy(h->pBuffer, b.data.data() + b.offset, count);
                h->nOffset = 0; h->nFilledLen = count; h->nFlags = 0;
                h->nTimeStamp = b.pts + av_rescale(b.offset / (channels * 2), 1000000, rate);
                b.offset += count;
                if (b.offset == b.data.size()) pending.pop_front();
                out->mOwnedByUs = false; oq.erase(oq.begin()); notifyFillBufferDone(h);
                continue;
            }
            if (eos) {
                BufferInfo *out = *oq.begin(); auto *h = out->mHeader;
                h->nOffset = h->nFilledLen = 0; h->nFlags = OMX_BUFFERFLAG_EOS; h->nTimeStamp = nextPts();
                eos = false; out->mOwnedByUs = false; oq.erase(oq.begin()); notifyFillBufferDone(h); return;
            }
            if (iq.empty()) return;
            BufferInfo *in = *iq.begin(); auto *h = in->mHeader;
            bool ok = decodeInput(h);
            h->nFilledLen = 0; in->mOwnedByUs = false; iq.erase(iq.begin()); notifyEmptyBufferDone(h);
            if (!ok) { fail(OMX_ErrorStreamCorrupt); return; }
        }
    }
    void onPortFlushCompleted(OMX_U32 port) override {
        if (port == 0) {
            closeDecoder(); pending.clear(); extra.clear(); eos = error = havePts = false; samples = 0;
            ALOGI("%s flush: decoder/parser/PCM/PTS reset", spec.name);
        } else if (!changing) { pending.clear(); }
    }
    void onPortEnableCompleted(OMX_U32 port, bool enabled) override {
        if (port != 1) return;
        if (changing == 1 && !enabled) changing = 2;
        else if (changing == 2 && enabled) { changing = 0; onQueueFilled(1); }
    }
    void onReset() override {
        closeDecoder(); pending.clear(); extra.clear(); changing = 0; eos = error = havePts = false; samples = 0;
    }
private:
    const CodecSpec &spec;
    AVCodecContext *context = nullptr;
    AVCodecParserContext *parser = nullptr;
    AVFrame *frame = nullptr;
    SwrContext *swr = nullptr;
    AVChannelLayout swrLayout{};
    int swrRate = 0, swrFormat = -1;
    int channels = 2, rate = 48000, changing = 0;
    OMX_AUDIO_CHANNELTYPE mapping[OMX_AUDIO_MAXCHANNELS]{};
    bool eos = false, error = false, havePts = false;
    int64_t anchorPts = 0, samples = 0;
    int clockRate = 48000;
    std::deque<PcmBlock> pending;
    std::vector<uint8_t> extra;
    static size_t pcmTargetBytes(const PcmBlock &b) {
        return std::min<size_t>(65536, std::max(1, b.rate / 50) * b.channels * 2);
    }
    int64_t nextPts() const { return anchorPts + av_rescale(samples, 1000000, clockRate); }
    void fail(OMX_ERRORTYPE e) { error = true; ALOGE("%s error 0x%x", spec.name, e); notify(OMX_EventError, e, 0, nullptr); }
    void closeDecoder() {
        avcodec_free_context(&context); if (parser) av_parser_close(parser); parser = nullptr;
        av_frame_free(&frame); swr_free(&swr); av_channel_layout_uninit(&swrLayout);
        swrRate = 0; swrFormat = -1;
    }
    bool openDecoder() {
        if (context) return true;
        context = avcodec_alloc_context3(avcodec_find_decoder(spec.id));
        frame = av_frame_alloc(); parser = av_parser_init(spec.id);
        if (!context || !frame || !parser) { ALOGE("%s missing context/frame/parser", spec.name); return false; }
        context->pkt_timebase = AVRational{1, 1000000}; context->thread_count = 1;
        if (!extra.empty()) {
            context->extradata = static_cast<uint8_t *>(av_mallocz(extra.size() + AV_INPUT_BUFFER_PADDING_SIZE));
            if (!context->extradata) return false;
            memcpy(context->extradata, extra.data(), extra.size()); context->extradata_size = extra.size();
        }
        int rc = avcodec_open2(context, context->codec, nullptr);
        if (rc < 0) ALOGE("%s avcodec_open2=%d", spec.name, rc);
        return rc >= 0;
    }
    bool receive() {
        for (;;) {
            int rc = avcodec_receive_frame(context, frame);
            if (rc == AVERROR(EAGAIN) || rc == AVERROR_EOF) return true;
            if (rc < 0) { ALOGW("%s dropped decode error %d", spec.name, rc); return true; }
            int ch = frame->ch_layout.nb_channels, sr = frame->sample_rate;
            if (ch < 1 || ch > 8 || sr < 8000 || sr > 192000 || frame->nb_samples > 32768) {
                ALOGE("%s invalid frame ch=%d rate=%d samples=%d", spec.name, ch, sr, frame->nb_samples); return false;
            }
            // Compatibility PCM output is stereo. swresample builds the
            // standard channel-layout downmix, retaining centre/surround audio
            // in L/R with normalization rather than discarding those channels.
            ch = 2;
            AVChannelLayout outputLayout = AV_CHANNEL_LAYOUT_STEREO;
            if (!swr || swrRate != sr || swrFormat != frame->format || av_channel_layout_compare(&swrLayout, &frame->ch_layout)) {
                swr_free(&swr); av_channel_layout_uninit(&swrLayout);
                if (swr_alloc_set_opts2(&swr, &outputLayout, AV_SAMPLE_FMT_S16, sr,
                                       &frame->ch_layout, (AVSampleFormat)frame->format, sr, 0, nullptr) < 0 || swr_init(swr) < 0) return false;
                av_channel_layout_copy(&swrLayout, &frame->ch_layout); swrRate = sr; swrFormat = frame->format;
                ALOGI("%s downmix %d source channels -> stereo PCM16 %d Hz", spec.name, frame->ch_layout.nb_channels, sr);
            }
            PcmBlock block; block.channels = ch; block.rate = sr;
            for (int i = 0; i < ch; ++i) block.map[i] = channelType(av_channel_layout_channel_from_index(&outputLayout, i));
            block.data.resize((frame->nb_samples + 64) * ch * 2);
            uint8_t *dst = block.data.data();
            int n = swr_convert(swr, &dst, frame->nb_samples + 64, const_cast<const uint8_t **>(frame->extended_data), frame->nb_samples);
            if (n < 0) return false;
            if (sr != clockRate) { anchorPts = nextPts(); samples = 0; clockRate = sr; }
            block.pts = nextPts(); samples += n; block.data.resize(n * ch * 2);
            if (n) {
                bool merged = false;
                if (spec.id == AV_CODEC_ID_TRUEHD && !pending.empty()) {
                    auto &tail = pending.back();
                    if (!tail.offset && tail.channels == block.channels && tail.rate == block.rate &&
                        !memcmp(tail.map, block.map, sizeof(tail.map)) &&
                        tail.data.size() + block.data.size() <= pcmTargetBytes(block)) {
                        if (tail.data.capacity() < pcmTargetBytes(block)) tail.data.reserve(pcmTargetBytes(block));
                        tail.data.insert(tail.data.end(), block.data.begin(), block.data.end());
                        merged = true;
                    }
                }
                if (!merged) pending.push_back(std::move(block));
            }
            av_frame_unref(frame);
            if (pending.size() > 8192) return false;
        }
    }
    bool send(const uint8_t *data, int size, int64_t pts) {
        AVPacket *pkt = av_packet_alloc();
        if (!pkt || av_new_packet(pkt, size) < 0) { av_packet_free(&pkt); return false; }
        memcpy(pkt->data, data, size); pkt->pts = pts; pkt->dts = pts;
        int rc = avcodec_send_packet(context, pkt);
        if (rc == AVERROR(EAGAIN)) { if (!receive()) { av_packet_free(&pkt); return false; } rc = avcodec_send_packet(context, pkt); }
        av_packet_free(&pkt);
        if (rc < 0) { ALOGW("%s skip invalid packet %d", spec.name, rc); return true; }
        return receive();
    }
    bool decodeInput(OMX_BUFFERHEADERTYPE *h) {
        if (h->nOffset > h->nAllocLen || h->nFilledLen > h->nAllocLen - h->nOffset) return false;
        if (h->nFlags & OMX_BUFFERFLAG_CODECCONFIG) {
            if (context || h->nFilledLen > 65536) return false;
            extra.assign(h->pBuffer + h->nOffset, h->pBuffer + h->nOffset + h->nFilledLen); return true;
        }
        if (!openDecoder()) return false;
        if (!havePts && h->nFilledLen) { anchorPts = h->nTimeStamp; samples = 0; havePts = true; }
        std::vector<uint8_t> input(h->nFilledLen + AV_INPUT_BUFFER_PADDING_SIZE, 0);
        if (h->nFilledLen) memcpy(input.data(), h->pBuffer + h->nOffset, h->nFilledLen);
        int offset = 0, iterations = 0, stalled = 0;
        while (offset < (int)h->nFilledLen) {
            uint8_t *packet = nullptr; int len = 0;
            int used = av_parser_parse2(parser, context, &packet, &len, input.data() + offset, h->nFilledLen - offset,
                                        offset == 0 ? h->nTimeStamp : AV_NOPTS_VALUE, AV_NOPTS_VALUE, -1);
            if (used < 0 || ++iterations > 8192) { ALOGE("%s parse used=%d", spec.name, used); return false; }
            offset += used;
            if (len && !send(packet, len, parser->pts)) return false;
            // MLP/TrueHD returns 0 once after finding major sync, then parses
            // the same bytes in its new state. Retry while bounding malformed input.
            if (!used && !len) {
                if (++stalled > 8) { ALOGE("%s parser stalled at %d/%u", spec.name, offset, h->nFilledLen); return false; }
            } else stalled = 0;
        }
        if (h->nFlags & OMX_BUFFERFLAG_EOS) {
            uint8_t *packet = nullptr; int len = 0;
            av_parser_parse2(parser, context, &packet, &len, nullptr, 0, AV_NOPTS_VALUE, AV_NOPTS_VALUE, -1);
            if (len && !send(packet, len, parser->pts)) return false;
            avcodec_send_packet(context, nullptr); if (!receive()) return false; eos = true;
        }
        return true;
    }
};

class SurroundPlugin final : public OMXPluginBase {
public:
    SurroundPlugin() {
        // Original hardware plugin is preserved verbatim under a private name.
        // Delegate video and unrelated audio codecs, including vendor tunnels.
        originalHandle = dlopen("libstagefrighthw_original.so", RTLD_NOW | RTLD_NODELETE);
        if (originalHandle) {
            auto create = reinterpret_cast<OMXPluginBase *(*)()>(dlsym(originalHandle, "createOMXPlugin"));
            if (!create) create = reinterpret_cast<OMXPluginBase *(*)()>(dlsym(originalHandle, "_ZN7android15createOMXPluginEv"));
            original = create ? create() : nullptr;
            destroyOriginal = reinterpret_cast<void (*)(OMXPluginBase *)>(dlsym(originalHandle, "destroyOMXPlugin"));
        }
        if (!original) ALOGE("original OMX plugin unavailable: %s", dlerror());
    }
    ~SurroundPlugin() override {
        if (original && destroyOriginal) destroyOriginal(original);
        else delete original;
        if (originalHandle) dlclose(originalHandle);
    }
    OMX_ERRORTYPE makeComponentInstance(const char *name, const OMX_CALLBACKTYPE *cb, OMX_PTR app, OMX_COMPONENTTYPE **component) override {
        const CodecSpec *s = findSpec(name);
        if (!s) return original ? original->makeComponentInstance(name, cb, app, component) : OMX_ErrorComponentNotFound;
        sp<SurroundDecoder> codec = new SurroundDecoder(*s, cb, app, component);
        if (codec->initCheck() != OMX_ErrorNone) return OMX_ErrorComponentNotFound;
        codec->incStrong(this);
        { Mutex::Autolock lock(instancesLock); instances.push_back(*component); }
        return OMX_ErrorNone;
    }
    OMX_ERRORTYPE destroyComponentInstance(OMX_COMPONENTTYPE *component) override {
        bool ours = false;
        {
            Mutex::Autolock lock(instancesLock);
            auto it = std::find(instances.begin(), instances.end(), component);
            if (it != instances.end()) { ours = true; instances.erase(it); }
        }
        if (!ours) return original ? original->destroyComponentInstance(component) : OMX_ErrorComponentNotFound;
        auto *codec = static_cast<SurroundDecoder *>(component->pComponentPrivate);
        codec->prepareForDestruction(); codec->decStrong(this); return OMX_ErrorNone;
    }
    OMX_ERRORTYPE enumerateComponents(OMX_STRING name, size_t size, OMX_U32 index) override {
        if (index < sizeof(specs) / sizeof(specs[0])) {
            if (size <= strlen(specs[index].name)) return OMX_ErrorBadParameter;
            strcpy(name, specs[index].name); return OMX_ErrorNone;
        }
        return original ? original->enumerateComponents(name, size, index - sizeof(specs) / sizeof(specs[0])) : OMX_ErrorNoMore;
    }
    OMX_ERRORTYPE getRolesOfComponent(const char *name, Vector<String8> *roles) override {
        if (const CodecSpec *s = findSpec(name)) { roles->clear(); roles->push(String8(s->role)); return OMX_ErrorNone; }
        return original ? original->getRolesOfComponent(name, roles) : OMX_ErrorComponentNotFound;
    }
    OMX_ERRORTYPE setupTunnel(OMX_COMPONENTTYPE *output, OMX_U32 outputPort, OMX_COMPONENTTYPE *input, OMX_U32 inputPort) override {
        { Mutex::Autolock lock(instancesLock);
          for (auto *c : instances) if (c == output || c == input) return OMX_ErrorNotImplemented; }
        return original ? original->setupTunnel(output, outputPort, input, inputPort) : OMX_ErrorNotImplemented;
    }
private:
    void *originalHandle = nullptr;
    OMXPluginBase *original = nullptr;
    void (*destroyOriginal)(OMXPluginBase *) = nullptr;
    Mutex instancesLock;
    std::vector<OMX_COMPONENTTYPE *> instances;
};
} // namespace android

extern "C" android::OMXPluginBase *createOMXPlugin() { return new android::SurroundPlugin; }
extern "C" void destroyOMXPlugin(android::OMXPluginBase *p) { delete p; }
