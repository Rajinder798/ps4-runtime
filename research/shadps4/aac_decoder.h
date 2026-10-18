// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <span>
#include <vector>

#ifndef PS4_RUNTIME_AAC_PARSER_ONLY
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavutil/error.h>
#include <libavutil/mem.h>
#include <libswresample/swresample.h>
}
#endif

namespace Core::ResearchAac {
enum class Status { Ready, Frame, NeedInput, Invalid, Unsupported, NotInitialized, NoMemory };
enum class Mode { Adts, Raw };
enum class Format { S16, S32, Float };
inline constexpr std::array<unsigned, 12> Rates = {
    96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000};
inline constexpr unsigned SamplesPerFrame = 1024;
inline constexpr unsigned BytesPerSample(Format format) { return format == Format::S16 ? 2 : 4; }

struct PacketInfo {
    Status status = Status::NeedInput;
    unsigned bytes = 0;
    unsigned channels = 0;
    unsigned rate = 0;
};

// One complete ADTS AAC-LC raw_data_block; no speculative reads or buffering
// of a caller's incomplete job. CRC and multi-block/PCE/HE layouts are outside
// this initial replacement's tested contract.
inline PacketInfo InspectAdts(std::span<const std::uint8_t> input) {
    if (input.size() < 7) return {};
    if (input[0] != 0xff || (input[1] & 0xf6) != 0xf0) return {Status::Invalid};
    const unsigned length = ((input[3] & 3u) << 11) | (unsigned(input[4]) << 3) | (input[5] >> 5);
    if (length < 7) return {Status::Invalid};
    if (input.size() < length) return {};
    const unsigned index = (input[2] >> 2) & 15;
    const unsigned channels = ((input[2] & 1u) << 2) | (input[3] >> 6);
    if ((input[2] >> 6) != 1 || index >= Rates.size() || channels < 1 || channels > 2 ||
        !(input[1] & 1) || (input[6] & 3)) return {Status::Unsupported};
    return {Status::Ready, length, channels, Rates[index]};
}

struct Range {
    unsigned skipped, samples, byte_offset, bytes;
};
inline Range OutputRange(unsigned channels, unsigned bytes_per_sample, unsigned skip,
                         unsigned limit) {
    const auto skipped = std::min(skip, SamplesPerFrame);
    const auto samples = std::min(limit, SamplesPerFrame - skipped);
    return {skipped, samples, skipped * channels * bytes_per_sample,
            samples * channels * bytes_per_sample};
}

#ifndef PS4_RUNTIME_AAC_PARSER_ONLY
struct DecodeResult {
    Status status;
    unsigned consumed = 0;
    int error = 0;
};

// Native FFmpeg AAC only. Own padded packet/frame/conversion buffers; never
// retain caller pointers. The AJM adapter preflights output space before Decode.
class Decoder {
public:
    Decoder() = default;
    Decoder(const Decoder&) = delete;
    Decoder& operator=(const Decoder&) = delete;
    ~Decoder() { Close(); }

    Status Initialize(Mode mode, unsigned rate_index, unsigned channels, Format format) {
        Close();
        mode_ = mode;
        format_ = format;
        channels_ = 0;
        rate_ = 0;
        if ((mode != Mode::Adts && mode != Mode::Raw) ||
            (format != Format::S16 && format != Format::S32 && format != Format::Float) ||
            channels > 2 || (mode == Mode::Raw && rate_index >= Rates.size()))
            return Status::Unsupported;
        const AVCodec* codec = avcodec_find_decoder_by_name("aac");
        if (!codec || codec->id != AV_CODEC_ID_AAC) return Status::Unsupported;
        context_ = avcodec_alloc_context3(codec);
        packet_ = av_packet_alloc();
        frame_ = av_frame_alloc();
        extra_ = av_frame_alloc();
        if (!context_ || !packet_ || !frame_ || !extra_) { Close(); return Status::NoMemory; }
        context_->err_recognition = AV_EF_CAREFUL | AV_EF_EXPLODE;
        context_->thread_count = 1;
        if (mode == Mode::Raw) {
            channels_ = channels ? channels : 2;
            rate_ = Rates[rate_index];
            context_->extradata_size = 2;
            context_->extradata = static_cast<std::uint8_t*>(av_mallocz(2 + AV_INPUT_BUFFER_PADDING_SIZE));
            if (!context_->extradata) { Close(); return Status::NoMemory; }
            // MPEG-4 AudioSpecificConfig: AAC-LC, indexed rate, mono/stereo.
            context_->extradata[0] = static_cast<std::uint8_t>((2u << 3) | (rate_index >> 1));
            context_->extradata[1] = static_cast<std::uint8_t>(((rate_index & 1) << 7) | (channels_ << 3));
        }
        if (avcodec_open2(context_, codec, nullptr) < 0) { Close(); return Status::Unsupported; }
        initialized_ = true;
        return Status::Ready;
    }

    PacketInfo Probe(std::span<const std::uint8_t> input) const {
        if (!initialized_) return {Status::NotInitialized};
        if (mode_ == Mode::Adts) return InspectAdts(input);
        if (input.empty()) return {};
        if (input.size() > 8191) return {Status::Unsupported};
        return {Status::Ready, static_cast<unsigned>(input.size()), channels_, rate_};
    }

    DecodeResult Decode(std::span<const std::uint8_t> input) {
        pcm_.clear();
        const auto info = Probe(input);
        if (info.status != Status::Ready) return {info.status};
        av_packet_unref(packet_);
        av_frame_unref(frame_);
        av_frame_unref(extra_);
        int result = av_new_packet(packet_, static_cast<int>(info.bytes));
        if (result < 0) return {Status::NoMemory, 0, result};
        std::memcpy(packet_->data, input.data(), info.bytes); // av_new_packet provides zero padding.
        result = avcodec_send_packet(context_, packet_);
        av_packet_unref(packet_);
        if (result < 0) return {Status::Invalid, 0, result};
        result = avcodec_receive_frame(context_, frame_);
        if (result == AVERROR(EAGAIN)) return {Status::NeedInput, info.bytes};
        if (result < 0) return {Status::Invalid, info.bytes, result};
        // A raw AJM input must contain exactly one access unit. Reject rather
        // than silently dropping any second frame retained in FFmpeg's queue.
        result = avcodec_receive_frame(context_, extra_);
        if (result != AVERROR(EAGAIN)) {
            initialized_ = false;
            return {Status::Unsupported, info.bytes, result};
        }
        if (frame_->nb_samples != static_cast<int>(SamplesPerFrame) ||
            frame_->ch_layout.nb_channels != static_cast<int>(info.channels) ||
            frame_->sample_rate != static_cast<int>(info.rate) ||
            context_->profile != AV_PROFILE_AAC_LOW) {
            initialized_ = false;
            return {Status::Unsupported, info.bytes};
        }
        channels_ = info.channels;
        rate_ = info.rate;
        const AVSampleFormat target = format_ == Format::S16 ? AV_SAMPLE_FMT_S16
                                      : format_ == Format::S32 ? AV_SAMPLE_FMT_S32 : AV_SAMPLE_FMT_FLT;
        swr_free(&converter_);
        result = swr_alloc_set_opts2(&converter_, &frame_->ch_layout, target, frame_->sample_rate,
                                    &frame_->ch_layout, static_cast<AVSampleFormat>(frame_->format),
                                    frame_->sample_rate, 0, nullptr);
        if (result >= 0) result = swr_init(converter_);
        if (result < 0) return {Status::Invalid, info.bytes, result};
        pcm_.resize(SamplesPerFrame * channels_ * BytesPerSample(format_));
        std::uint8_t* destination[] = {pcm_.data()};
        std::array<const std::uint8_t*, 2> source{};
        for (unsigned c = 0; c < channels_; ++c) source[c] = frame_->extended_data[c];
        result = swr_convert(converter_, destination, static_cast<int>(SamplesPerFrame),
                             source.data(), frame_->nb_samples);
        if (result != static_cast<int>(SamplesPerFrame)) {
            pcm_.clear();
            return {Status::Invalid, info.bytes, result};
        }
        return {Status::Frame, info.bytes};
    }

    std::span<const std::uint8_t> Pcm() const { return pcm_; }
    unsigned Channels() const { return channels_; }
    unsigned Rate() const { return rate_; }
    Format Encoding() const { return format_; }

private:
    void Close() {
        initialized_ = false;
        swr_free(&converter_);
        av_frame_free(&extra_);
        av_frame_free(&frame_);
        av_packet_free(&packet_);
        avcodec_free_context(&context_);
        pcm_.clear();
    }
    bool initialized_ = false;
    Mode mode_ = Mode::Adts;
    Format format_ = Format::S16;
    unsigned channels_ = 0, rate_ = 0;
    AVCodecContext* context_ = nullptr;
    AVPacket* packet_ = nullptr;
    AVFrame* frame_ = nullptr;
    AVFrame* extra_ = nullptr;
    SwrContext* converter_ = nullptr;
    std::vector<std::uint8_t> pcm_;
};
#endif
} // namespace Core::ResearchAac
