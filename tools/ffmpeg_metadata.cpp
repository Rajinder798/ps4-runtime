// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

// Host-only audit helper. Query the linked libraries; do not decode guest media.
#include <iostream>
#include <string_view>
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavfilter/avfilter.h>
#include <libavformat/avformat.h>
#include <libavutil/avutil.h>
#include <libswresample/swresample.h>
#include <libswscale/swscale.h>
}

void Json(std::string_view value) {
    constexpr char hex[] = "0123456789abcdef";
    std::cout << '"';
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') std::cout << '\\' << static_cast<char>(c);
        else if (c < 32) std::cout << "\\u00" << hex[c >> 4] << hex[c & 15];
        else std::cout << static_cast<char>(c);
    }
    std::cout << '"';
}

void Library(const char* name, unsigned headers, unsigned binary, const char* license,
             const char* configuration, bool comma) {
    if (comma) std::cout << ',';
    Json(name);
    std::cout << ":{\"header_version\":" << headers << ",\"binary_version\":" << binary
              << ",\"license\":";
    Json(license);
    std::cout << ",\"configuration\":";
    Json(configuration);
    std::cout << '}';
}

int main() {
    std::cout << "{\"schema_version\":1,\"ffmpeg_version\":";
    Json(av_version_info());
    std::cout << ",\"libraries\":{";
    Library("avcodec", LIBAVCODEC_VERSION_INT, avcodec_version(), avcodec_license(),
            avcodec_configuration(), false);
    Library("avfilter", LIBAVFILTER_VERSION_INT, avfilter_version(), avfilter_license(),
            avfilter_configuration(), true);
    Library("avformat", LIBAVFORMAT_VERSION_INT, avformat_version(), avformat_license(),
            avformat_configuration(), true);
    Library("avutil", LIBAVUTIL_VERSION_INT, avutil_version(), avutil_license(),
            avutil_configuration(), true);
    Library("swresample", LIBSWRESAMPLE_VERSION_INT, swresample_version(), swresample_license(),
            swresample_configuration(), true);
    Library("swscale", LIBSWSCALE_VERSION_INT, swscale_version(), swscale_license(),
            swscale_configuration(), true);
    std::cout << "}}\n";
    return std::cout ? 0 : 1;
}
