// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

// Compile with the actual patched ajm_aac.cpp. Only host logging and the small
// channel-mask utility are isolated here; no guest service/export is substituted.
#include "core/libraries/ajm/ajm_aac.h"
#include "core/libraries/ajm/ajm_result.h"
#include "fixtures/aac_tones.h"
#include <iostream>
#include <stdexcept>

namespace Common::Log {
std::array<Level, NUM_LOG_CLASSES> g_class_levels = [] {
    std::array<Level, NUM_LOG_CLASSES> levels{};
    levels.fill(Level::Off);
    return levels;
}();
void VLog(Class, Level, const char*, int, const char*, fmt::string_view, fmt::format_args) {
    throw std::runtime_error("Unexpected host log in adapter tests");
}
}
namespace Libraries::Ajm {
u32 GetChannelMask(u32 channels) {
    if (channels == 1) return 0x0004; // Pinned AJM mono mask.
    if (channels == 2) return 0x0003; // Pinned AJM stereo mask.
    throw std::runtime_error("Unexpected channel-mask query");
}
}
namespace J = Libraries::Ajm;
namespace A = Core::ResearchAac;
unsigned checks = 0;
void Check(bool value, const char* message) {
    ++checks;
    if (!value) throw std::runtime_error(message);
}

int main() {
    try {
        av_log_set_level(AV_LOG_QUIET);
        for (unsigned channels : {1u, 2u}) {
            const std::span<const u8> fixture = channels == 1 ? std::span<const u8>(AacFixtures::Mono)
                                                            : std::span<const u8>(AacFixtures::Stereo);
            const auto info = A::InspectAdts(fixture);
            for (auto format : {J::AjmFormatEncoding::S16, J::AjmFormatEncoding::S32, J::AjmFormatEncoding::Float}) {
                const auto native_format = format == J::AjmFormatEncoding::S16 ? A::Format::S16
                                         : format == J::AjmFormatEncoding::S32 ? A::Format::S32 : A::Format::Float;
                A::Decoder reference;
                Check(reference.Initialize(A::Mode::Adts, 0, channels, native_format) == A::Status::Ready, "Reference initialization");
                Check(reference.Decode(fixture).status == A::Status::Frame, "Reference decode");
                const unsigned width = A::BytesPerSample(native_format);
                J::AjmAacDecoder decoder(format, J::EnableNondelayOutput, channels);
                Check(decoder.GetFormat().num_channels == 0 && decoder.GetFormat().channel_mask == 0, "Unknown pre-stream format must not crash");
                J::AjmInstanceGapless gapless{};
                gapless.init.total_samples = 513;
                gapless.init.skip_samples = 37;
                gapless.Reset();
                const auto count = 513 * channels * width;
                std::vector<u8> storage(count + 32, 0xa5);
                std::vector<u8> source(fixture.begin(), fixture.end());
                std::span<u8> input(source);
                // First reject a short output before decoding or advancing input.
                std::array<std::span<u8>, 1> short_chunks{std::span(storage).subspan(16, count - 1)};
                J::SparseOutputBuffer short_output(short_chunks);
                const auto short_result = decoder.ProcessData(input, short_output, gapless);
                Check(short_result.result == ORBIS_AJM_RESULT_NOT_ENOUGH_ROOM, "Output capacity must be checked");
                Check(input.size() == source.size() && gapless.current.skip_samples == 37 &&
                      gapless.current.total_samples == 513, "Short output must not consume input/gapless state");
                Check(std::ranges::all_of(storage, [](auto b) { return b == 0xa5; }), "Short output must write no bytes");
                // Odd chunk boundaries exercise byte-accurate sparse PCM writes.
                std::array<std::span<u8>, 3> chunks{std::span(storage).subspan(16, 1),
                    std::span(storage).subspan(17, 3), std::span(storage).subspan(20, count - 4)};
                J::SparseOutputBuffer output(chunks);
                const auto result = decoder.ProcessData(input, output, gapless);
                Check(result.result == 0 && result.frames_decoded == 1 && result.samples_written == 513, "Actual adapter decode/trim counts");
                Check(input.size() == source.size() - info.bytes && output.Size() == 0, "Exact input/output accounting");
                Check(gapless.current.skip_samples == 0 && gapless.current.total_samples == 0 &&
                      gapless.current.skipped_samples == 511, "Gapless accounting");
                Check(std::memcmp(storage.data() + 16, reference.Pcm().data() + 37 * channels * width, count) == 0,
                      "Adapter must output the selected decoded samples");
                Check(std::ranges::all_of(std::span(storage).first(16), [](auto b) { return b == 0xa5; }) &&
                      std::ranges::all_of(std::span(storage).last(16), [](auto b) { return b == 0xa5; }), "PCM guards preserved");
                Check(decoder.GetFormat().num_channels == channels && decoder.GetFormat().sampl_freq == info.rate,
                      "Actual adapter format metadata");
                decoder.Reset();
                gapless = {};
                input = source;
                std::vector<u8> whole(1024 * channels * width);
                std::array<std::span<u8>, 1> whole_chunks{whole};
                J::SparseOutputBuffer whole_output(whole_chunks);
                Check(decoder.ProcessData(input, whole_output, gapless).result == 0, "Adapter reset decode");
                Check(std::ranges::equal(whole, reference.Pcm()), "Adapter reset must restore PCM state");
                const std::array<u32, 2> raw_config{J::ConfigType::RAW, channels == 1 ? 4u : 3u};
                decoder.Initialize(raw_config.data(), sizeof(raw_config));
                source.assign(fixture.begin() + 7, fixture.begin() + info.bytes);
                input = source;
                whole_chunks = {whole};
                J::SparseOutputBuffer raw_output(whole_chunks);
                Check(decoder.ProcessData(input, raw_output, gapless).result == 0 && input.empty(), "Actual adapter raw configuration/decode");
                Check(std::ranges::equal(whole, reference.Pcm()), "Raw adapter PCM matches ADTS");
                decoder.Initialize(nullptr, 8);
                input = source;
                whole_chunks = {whole};
                J::SparseOutputBuffer invalid_output(whole_chunks);
                Check(decoder.ProcessData(input, invalid_output, gapless).result == ORBIS_AJM_RESULT_INVALID_PARAMETER,
                      "Invalid initialization returns an error");
                Check(input.size() == source.size(), "Invalid initialization consumes nothing");
            }
            // Preserve the existing two-frame prefill when nondelay is absent.
            J::AjmAacDecoder delayed(J::AjmFormatEncoding::S16, J::AjmAacCodecFlags{}, channels);
            std::vector<u8> source(fixture.begin(), fixture.end());
            std::span<u8> input(source);
            J::AjmInstanceGapless gapless{};
            std::array<std::span<u8>, 0> none{};
            J::SparseOutputBuffer no_output(none);
            for (int i = 0; i < 2; ++i) {
                Check(delayed.GetNextFrameSize(gapless) == 0, "Prefill needs no output space");
                const auto result = delayed.ProcessData(input, no_output, gapless);
                Check(result.result == 0 && result.frames_decoded == 1 && result.samples_written == 0,
                      "Prefill consumes frames without inventing PCM");
            }
            Check(delayed.GetNextFrameSize(gapless) == 1024 * channels * 2, "After prefill reserve an actual output frame");
        }
        std::vector<u8> stereo(std::begin(AacFixtures::Stereo), std::end(AacFixtures::Stereo));
        std::span<u8> input(stereo);
        std::vector<u8> buffer(8192, 0x5a);
        std::array<std::span<u8>, 1> chunks{buffer};
        J::SparseOutputBuffer output(chunks);
        J::AjmInstanceGapless gapless{};
        J::AjmAacDecoder mono(J::AjmFormatEncoding::S16, J::EnableNondelayOutput, 1);
        Check(mono.ProcessData(input, output, gapless).result == ORBIS_AJM_RESULT_STREAM_CHANGE &&
              input.size() == stereo.size(), "Configured mono must reject a stereo stream without consumption");
        J::AjmAacDecoder surround(J::AjmFormatEncoding::S16, J::EnableNondelayOutput, 6);
        Check(surround.ProcessData(input, output, gapless).result == ORBIS_AJM_RESULT_TOO_MANY_CHANNELS,
              "Untested surround configuration returns an error");
        J::AjmAacDecoder unsupported(J::AjmFormatEncoding::S16,
                                   J::SurroundChannelInterleaveOrderLsRsExtlExtr, 2);
        Check(unsupported.ProcessData(input, output, gapless).result == ORBIS_AJM_RESULT_UNSUPPORTED_FLAG,
              "Untested channel-order flags return an error");
        const std::array<u32, 2> bad_config{J::ConfigType::RAW, 12};
        mono.Initialize(bad_config.data(), sizeof(bad_config));
        Check(mono.ProcessData(input, output, gapless).result != 0 && input.size() == stereo.size(),
              "Invalid raw rate must not reach a stale decoder");
        J::AjmAacDecoder automatic(J::AjmFormatEncoding::S16, J::EnableNondelayOutput, 0);
        std::vector<u8> mono_source(std::begin(AacFixtures::Mono), std::end(AacFixtures::Mono));
        std::span<u8> mono_input(mono_source);
        Check(automatic.ProcessData(mono_input, output, gapless).result == 0,
              "Auto channel setup must decode mono");
        std::array<std::span<u8>, 1> small_chunks{std::span(buffer).first(2048)};
        J::SparseOutputBuffer small_output(small_chunks);
        Check(automatic.GetNextFrameSize(gapless) == 2048, "Previous mono frame predicts mono capacity");
        Check(automatic.ProcessData(input, small_output, gapless).result == ORBIS_AJM_RESULT_NOT_ENOUGH_ROOM &&
              input.size() == stereo.size(), "New stereo header must trigger a fresh capacity check before consumption");
        std::cout << "{\"schema_version\":1,\"status\":\"passed\",\"adapter_checks\":" << checks
                  << ",\"guest_audio_tested\":false}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "AJM AAC test: " << error.what() << '\n';
        return 1;
    }
}
