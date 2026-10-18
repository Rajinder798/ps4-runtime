// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#include "aac_decoder.h"
#include "fixtures/aac_tones.h"
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#endif

namespace A = Core::ResearchAac;
unsigned checks = 0;
void Check(bool value, const char* message) {
    ++checks;
    if (!value) throw std::runtime_error(message);
}
std::vector<std::uint8_t> Decode(std::span<const std::uint8_t> input, A::Decoder& decoder,
                                bool raw, unsigned channels, unsigned rate) {
    std::vector<std::uint8_t> output;
    while (!input.empty()) {
        const auto info = A::InspectAdts(input);
        Check(info.status == A::Status::Ready, "Fixture must contain complete ADTS frames");
        const auto packet = raw ? input.subspan(7, info.bytes - 7) : input;
        const auto result = decoder.Decode(packet);
        Check(result.status == A::Status::Frame, "Native AAC must decode a fixture frame");
        Check(result.consumed == (raw ? info.bytes - 7 : info.bytes), "Consume exactly one access unit");
        Check(decoder.Channels() == channels && decoder.Rate() == rate, "Decoded format must match tone source");
        Check(decoder.Pcm().size() == 1024 * channels * A::BytesPerSample(decoder.Encoding()), "PCM size must be exact");
        output.insert(output.end(), decoder.Pcm().begin(), decoder.Pcm().end());
        input = input.subspan(info.bytes);
    }
    return output;
}

std::vector<float> Floats(std::span<const std::uint8_t> bytes, A::Format format) {
    std::vector<float> result;
    const auto width = A::BytesPerSample(format);
    for (std::size_t i = 0; i < bytes.size(); i += width) {
        if (format == A::Format::Float) {
            float value;
            std::memcpy(&value, bytes.data() + i, sizeof(value));
            Check(std::isfinite(value), "Decoded samples must be finite");
            result.push_back(value);
        } else if (format == A::Format::S16) {
            std::int16_t value;
            std::memcpy(&value, bytes.data() + i, sizeof(value));
            result.push_back(float(value) / 32768.0f);
        } else {
            std::int32_t value;
            std::memcpy(&value, bytes.data() + i, sizeof(value));
            result.push_back(static_cast<float>(double(value) / 2147483648.0));
        }
    }
    return result;
}

void CheckTone(const std::vector<float>& samples, unsigned channels, unsigned rate) {
    Check(samples.size() >= 6 * 1024 * channels, "Enough decoded tone for spectral check");
    for (unsigned c = 0; c < channels; ++c) {
        double energy = 0, real = 0, imag = 0, wrong_real = 0, wrong_imag = 0;
        const double frequency = c == 0 ? 440.0 : 880.0;
        const double wrong = c == 0 ? 880.0 : 440.0;
        std::size_t count = 0;
        for (std::size_t i = 2 * 1024; i < samples.size() / channels; ++i) {
            const double sample = samples[i * channels + c];
            const double time = double(i) / rate;
            energy += sample * sample;
            real += sample * std::cos(6.283185307179586 * frequency * time);
            imag += sample * std::sin(6.283185307179586 * frequency * time);
            wrong_real += sample * std::cos(6.283185307179586 * wrong * time);
            wrong_imag += sample * std::sin(6.283185307179586 * wrong * time);
            ++count;
        }
        const double rms = std::sqrt(energy / double(count));
        const double amplitude = 2 * std::hypot(real, imag) / double(count);
        const double wrong_amplitude = 2 * std::hypot(wrong_real, wrong_imag) / double(count);
        Check(rms > 0.08 && rms < 0.3, "Non-silent decoded amplitude must match original sine input");
        Check(amplitude > 0.1 && amplitude < 0.35, "Expected independent source frequency must dominate");
        Check(wrong_amplitude < 0.04, "Channel order/frequency must not be swapped");
    }
}

int main() {
    try {
        av_log_set_level(AV_LOG_QUIET); // Expected malformed-input tests need no host log text.
        A::Decoder invalid;
        Check(invalid.Decode({}).status == A::Status::NotInitialized, "Uninitialized decoder must fail");
        Check(invalid.Initialize(A::Mode::Raw, 12, 2, A::Format::S16) == A::Status::Unsupported, "Reject unknown rate");
        Check(invalid.Initialize(A::Mode::Raw, 3, 6, A::Format::S16) == A::Status::Unsupported, "Reject untested channel layouts");
        for (unsigned channels : {1u, 2u}) {
            const std::span<const std::uint8_t> input = channels == 1
                ? std::span<const std::uint8_t>(AacFixtures::Mono)
                : std::span<const std::uint8_t>(AacFixtures::Stereo);
            const unsigned index = channels == 1 ? 4 : 3;
            const unsigned rate = A::Rates[index];
            std::vector<float> reference;
            for (auto format : {A::Format::Float, A::Format::S16, A::Format::S32}) {
                A::Decoder adts, raw;
                Check(adts.Initialize(A::Mode::Adts, 0, channels, format) == A::Status::Ready, "Open native ADTS AAC decoder");
                Check(raw.Initialize(A::Mode::Raw, index, channels, format) == A::Status::Ready, "Open raw AAC with standard ASC");
                auto decoded = Decode(input, adts, false, channels, rate);
                Check(decoded == Decode(input, raw, true, channels, rate), "ADTS and raw access units must produce identical PCM");
                Check(adts.Initialize(A::Mode::Adts, 0, channels, format) == A::Status::Ready, "Reset/reopen must succeed");
                Check(decoded == Decode(input, adts, false, channels, rate), "Reset must restore deterministic state");
                auto floats = Floats(decoded, format);
                CheckTone(floats, channels, rate);
                if (format == A::Format::Float) reference = floats;
                else {
                    Check(reference.size() == floats.size(), "PCM formats must preserve sample count");
                    const float tolerance = format == A::Format::S16 ? 0.000031f : 0.000001f;
                    bool match = true;
                    for (std::size_t i = 0; i < floats.size(); ++i) match &= std::abs(floats[i] - reference[i]) <= tolerance;
                    Check(match, "Integer conversion must match native float samples within quantization");
                }
            }
            A::Decoder decoder;
            Check(decoder.Initialize(A::Mode::Adts, 0, channels, A::Format::S16) == A::Status::Ready, "Open malformed-input test");
            const auto first = A::InspectAdts(input);
            for (unsigned size = 0; size < first.bytes; ++size) {
                const auto result = decoder.Decode(input.first(size));
                Check(result.status == A::Status::NeedInput && result.consumed == 0 && decoder.Pcm().empty(), "Truncated packet must consume/write nothing");
            }
            std::vector<std::uint8_t> malformed(input.begin(), input.begin() + first.bytes);
            malformed[0] = 0;
            Check(decoder.Decode(malformed).status == A::Status::Invalid, "Reject sync corruption");
            malformed.assign(input.begin(), input.begin() + first.bytes);
            std::fill(malformed.begin() + 7, malformed.end(), 0xff);
            const auto bad = decoder.Decode(malformed);
            Check(bad.status == A::Status::Invalid && decoder.Pcm().empty(), "Malformed payload must not report silence as successful decoding");
            Check(decoder.Initialize(A::Mode::Adts, 0, channels, A::Format::S16) == A::Status::Ready, "Reset after bad payload");
            Check(decoder.Decode(input).status == A::Status::Frame, "Valid frame must decode after reset");
            A::Decoder raw;
            Check(raw.Initialize(A::Mode::Raw, index, channels, A::Format::S16) == A::Status::Ready, "Raw multi-unit rejection setup");
            const auto second = A::InspectAdts(input.subspan(first.bytes));
            std::vector<std::uint8_t> joined(input.begin() + 7, input.begin() + first.bytes);
            joined.insert(joined.end(), input.begin() + first.bytes + 7,
                          input.begin() + first.bytes + second.bytes);
            const auto multiple = raw.Decode(joined);
            Check(multiple.status != A::Status::Frame && raw.Pcm().empty(), "Raw concatenated access units must not silently lose a second frame");
#ifdef _WIN32
            SYSTEM_INFO system{};
            GetSystemInfo(&system);
            auto* pages = static_cast<std::uint8_t*>(VirtualAlloc(nullptr, system.dwPageSize * 2,
                                                               MEM_RESERVE, PAGE_NOACCESS));
            Check(pages != nullptr, "Reserve guarded input");
            Check(VirtualAlloc(pages, system.dwPageSize, MEM_COMMIT, PAGE_READWRITE) != nullptr,
                  "Commit input page only");
            Check(first.bytes < system.dwPageSize, "Fixture fits guard page");
            auto* end_aligned = pages + system.dwPageSize - first.bytes;
            std::memcpy(end_aligned, input.data(), first.bytes);
            Check(decoder.Initialize(A::Mode::Adts, 0, channels, A::Format::S16) == A::Status::Ready,
                  "Guarded input decoder");
            Check(decoder.Decode({end_aligned, first.bytes}).status == A::Status::Frame,
                  "Decoder must supply padding without reading past caller input");
            Check(VirtualFree(pages, 0, MEM_RELEASE) != 0, "Free guarded input");
#endif
        }
        std::cout << "{\"schema_version\":1,\"status\":\"passed\",\"checks\":" << checks
                  << ",\"native_decoder\":\"aac\",\"guest_audio_tested\":false}\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "AAC test: " << error.what() << '\n';
        return 1;
    }
}
