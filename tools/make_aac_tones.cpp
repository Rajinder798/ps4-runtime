// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

// Original deterministic tone input, encoded locally by Windows Media Foundation.
// This generator is a test tool, never a runtime/encoder redistribution dependency.
#define NOMINMAX
#include <windows.h>
#include <mfapi.h>
#include <mferror.h>
#include <mfidl.h>
#include <mftransform.h>
#include <wmcodecdsp.h>
#include <wrl/client.h>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using Microsoft::WRL::ComPtr;
void Check(HRESULT result) {
    if (FAILED(result)) throw std::runtime_error("Media Foundation error " + std::to_string(result));
}

std::vector<std::uint8_t> Encode(unsigned channels, unsigned rate) {
    ComPtr<IMFTransform> encoder;
    Check(CoCreateInstance(CLSID_AACMFTEncoder, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&encoder)));
    ComPtr<IMFMediaType> input, output;
    Check(MFCreateMediaType(&input));
    Check(MFCreateMediaType(&output));
    for (auto* type : {input.Get(), output.Get()}) {
        Check(type->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Audio));
        Check(type->SetUINT32(MF_MT_AUDIO_NUM_CHANNELS, channels));
        Check(type->SetUINT32(MF_MT_AUDIO_SAMPLES_PER_SECOND, rate));
        Check(type->SetUINT32(MF_MT_AUDIO_BITS_PER_SAMPLE, 16));
    }
    Check(input->SetGUID(MF_MT_SUBTYPE, MFAudioFormat_PCM));
    Check(output->SetGUID(MF_MT_SUBTYPE, MFAudioFormat_AAC));
    Check(output->SetUINT32(MF_MT_AUDIO_AVG_BYTES_PER_SECOND, 16000));
    Check(output->SetUINT32(MF_MT_AAC_PAYLOAD_TYPE, 1)); // ADTS; one 1024-sample AAC-LC block.
    Check(output->SetUINT32(MF_MT_AAC_AUDIO_PROFILE_LEVEL_INDICATION, 0x29));
    Check(encoder->SetInputType(0, input.Get(), 0));
    Check(encoder->SetOutputType(0, output.Get(), 0));
    Check(encoder->ProcessMessage(MFT_MESSAGE_NOTIFY_BEGIN_STREAMING, 0));
    Check(encoder->ProcessMessage(MFT_MESSAGE_NOTIFY_START_OF_STREAM, 0));
    MFT_OUTPUT_STREAM_INFO stream_info{};
    Check(encoder->GetOutputStreamInfo(0, &stream_info));
    std::vector<std::uint8_t> encoded;
    const auto receive = [&] {
        for (;;) {
            ComPtr<IMFSample> sample;
            ComPtr<IMFMediaBuffer> buffer;
            Check(MFCreateSample(&sample));
            Check(MFCreateMemoryBuffer(std::max<DWORD>(stream_info.cbSize, 16384), &buffer));
            Check(sample->AddBuffer(buffer.Get()));
            MFT_OUTPUT_DATA_BUFFER result{0, sample.Get(), 0, nullptr};
            DWORD status = 0;
            HRESULT code = encoder->ProcessOutput(0, 1, &result, &status);
            if (result.pEvents) result.pEvents->Release();
            if (code == MF_E_TRANSFORM_NEED_MORE_INPUT) return;
            Check(code);
            BYTE* bytes = nullptr;
            DWORD size = 0;
            Check(buffer->Lock(&bytes, nullptr, &size));
            encoded.insert(encoded.end(), bytes, bytes + size);
            Check(buffer->Unlock());
        }
    };
    constexpr unsigned block_samples = 1024;
    for (unsigned block = 0; block < 8; ++block) {
        ComPtr<IMFSample> sample;
        ComPtr<IMFMediaBuffer> buffer;
        Check(MFCreateSample(&sample));
        const DWORD bytes = block_samples * channels * sizeof(std::int16_t);
        Check(MFCreateMemoryBuffer(bytes, &buffer));
        BYTE* memory = nullptr;
        Check(buffer->Lock(&memory, nullptr, nullptr));
        auto* pcm = reinterpret_cast<std::int16_t*>(memory);
        for (unsigned i = 0; i < block_samples; ++i) {
            for (unsigned c = 0; c < channels; ++c) {
                const double time = double(block * block_samples + i) / rate;
                const double frequency = c == 0 ? 440.0 : 880.0;
                pcm[i * channels + c] = static_cast<std::int16_t>(
                    std::lround(8192.0 * std::sin(6.283185307179586 * frequency * time)));
            }
        }
        Check(buffer->Unlock());
        Check(buffer->SetCurrentLength(bytes));
        Check(sample->AddBuffer(buffer.Get()));
        Check(sample->SetSampleTime((LONGLONG(block) * block_samples * 10000000) / rate));
        Check(sample->SetSampleDuration((LONGLONG(block_samples) * 10000000) / rate));
        Check(encoder->ProcessInput(0, sample.Get(), 0));
        receive();
    }
    Check(encoder->ProcessMessage(MFT_MESSAGE_NOTIFY_END_OF_STREAM, 0));
    Check(encoder->ProcessMessage(MFT_MESSAGE_COMMAND_DRAIN, 0));
    receive();
    return encoded;
}

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    try {
        Check(CoInitializeEx(nullptr, COINIT_MULTITHREADED));
        Check(MFStartup(MF_VERSION));
        std::ofstream output(argv[1], std::ios::binary);
        if (!output) throw std::runtime_error("Cannot create fixture header");
        output << "// SPDX-FileCopyrightText: 2026 Rajinder Singh\n"
                  "// SPDX-License-Identifier: GPL-2.0-or-later\n"
                  "// Original 440 Hz / 880 Hz sine input encoded by tools/make_aac_tones.cpp.\n"
                  "#pragma once\n#include <cstdint>\nnamespace AacFixtures {\n";
        for (unsigned channels : {1u, 2u}) {
            const unsigned rate = channels == 1 ? 44100 : 48000;
            const auto data = Encode(channels, rate);
            output << "inline constexpr std::uint8_t " << (channels == 1 ? "Mono" : "Stereo") << "[] = {\n";
            for (std::size_t i = 0; i < data.size(); ++i) {
                if (i % 16 == 0) output << "    ";
                output << "0x" << std::hex << std::setw(2) << std::setfill('0') << unsigned(data[i]) << ',';
                output << ((i % 16 == 15 || i + 1 == data.size()) ? '\n' : ' ');
            }
            output << "\n};\n" << std::dec;
            std::cout << channels << " channels: " << data.size() << " ADTS bytes\n";
        }
        output << "}\n";
        if (!output) throw std::runtime_error("Cannot write fixtures");
        Check(MFShutdown());
        CoUninitialize();
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
