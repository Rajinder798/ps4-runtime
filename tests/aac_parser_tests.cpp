// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

#include "aac_decoder.h"
#include "fixtures/aac_tones.h"
#include <iostream>
#include <random>
#include <stdexcept>

namespace A = Core::ResearchAac;
unsigned checks = 0;
void Check(bool value) {
    ++checks;
    if (!value) throw std::runtime_error("AAC parser/range check failed");
}
int main() {
    try {
        for (auto stream : {std::span<const std::uint8_t>(AacFixtures::Mono),
                            std::span<const std::uint8_t>(AacFixtures::Stereo)}) {
            const auto first = A::InspectAdts(stream);
            Check(first.status == A::Status::Ready);
            for (unsigned length = 0; length < first.bytes; ++length) {
                const auto result = A::InspectAdts(stream.first(length));
                Check(result.status == A::Status::NeedInput && result.bytes == 0);
            }
            while (!stream.empty()) {
                const auto result = A::InspectAdts(stream);
                Check(result.status == A::Status::Ready && result.bytes >= 7 && result.bytes <= stream.size());
                Check(result.channels >= 1 && result.channels <= 2);
                stream = stream.subspan(result.bytes);
            }
        }
        std::vector<std::uint8_t> frame(std::begin(AacFixtures::Stereo), std::end(AacFixtures::Stereo));
        const auto valid = frame;
        frame[0] = 0;
        Check(A::InspectAdts(frame).status == A::Status::Invalid);
        frame = valid; frame[1] &= 0xfe;
        Check(A::InspectAdts(frame).status == A::Status::Unsupported); // CRC.
        frame = valid; frame[6] |= 1;
        Check(A::InspectAdts(frame).status == A::Status::Unsupported); // Multiple raw blocks.
        frame = valid; frame[2] |= 0xc0;
        Check(A::InspectAdts(frame).status == A::Status::Unsupported); // Non-LC profile.
        frame = valid; frame[2] = (frame[2] & 0xc3) | 0x3c;
        Check(A::InspectAdts(frame).status == A::Status::Unsupported); // Reserved rate.
        frame = valid; frame[2] &= 0xfe; frame[3] &= 0x3f;
        Check(A::InspectAdts(frame).status == A::Status::Unsupported); // PCE channel config.
        frame = valid; frame[3] |= 0xc0;
        Check(A::InspectAdts(frame).status == A::Status::Unsupported); // Three channels.
        frame = valid; frame[3] &= 0xfc; frame[4] = 0; frame[5] &= 0x1f;
        Check(A::InspectAdts(frame).status == A::Status::Invalid); // Invalid length.
        for (unsigned channels : {1u, 2u}) {
            for (unsigned width : {2u, 4u}) {
                for (unsigned skip : {0u, 37u, 1024u, 65535u}) {
                    for (unsigned limit : {0u, 1u, 513u, 1024u, UINT32_MAX}) {
                        const auto range = A::OutputRange(channels, width, skip, limit);
                        Check(range.skipped <= 1024 && range.samples <= limit &&
                              range.skipped + range.samples <= 1024);
                        Check(range.byte_offset + range.bytes <= 1024 * channels * width);
                        Check(range.bytes == range.samples * channels * width);
                    }
                }
            }
        }
        std::minstd_rand random(0xAAC);
        std::array<std::uint8_t, 32> bytes{};
        for (unsigned iteration = 0; iteration < 10000; ++iteration) {
            for (auto& byte : bytes) byte = static_cast<std::uint8_t>(random());
            const auto size = random() % (bytes.size() + 1);
            const auto result = A::InspectAdts(std::span(bytes).first(size));
            Check(result.status != A::Status::Ready ||
                  (result.bytes >= 7 && result.bytes <= size && result.channels >= 1 && result.channels <= 2));
        }
        std::cout << checks << " portable AAC framing/range checks passed (no decoder/guest execution)\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
