// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

// Local equivalence verification: compares the Windows CNG primitives in
// research/shadps4/p2p_crypto_cng.h against LibreSSL crypto.lib, replicating
// the exact OpenSSL calls made by shadPS4's src/core/net/p2p_crypto.cpp.
//
// Not built by CMake because the main build tree and CI do not link LibreSSL.
//
// To build and run manually in the Visual Studio x64 developer environment:
//   clang-cl -std:c++20 /MD /O2 -I research/shadps4 ^
//     -I build/upstream/shadps4-strict/externals/libressl/include ^
//     tests/p2p_crypto_libressl_compare.cpp ^
//     build/upstream/windows-x64-strict/externals/libressl/crypto/crypto.lib ^
//     bcrypt.lib ws2_32.lib advapi32.lib /Febuild/p2p_compare.exe
//   build/p2p_compare.exe
// Expected output: cases=8000 mismatches=0

#include "p2p_crypto_cng.h"

#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/hmac.h>

#include <cstdio>
#include <cstring>
#include <random>
#include <vector>

static bool OpenSslCfb(std::vector<std::uint8_t>& payload, const std::uint8_t* key, const std::uint8_t* iv, bool encrypt) {
    EVP_CIPHER_CTX* context = EVP_CIPHER_CTX_new();
    int output_size = 0, final_size = 0;
    const bool ok = EVP_CipherInit_ex(context, EVP_aes_128_cfb128(), nullptr, key, iv, encrypt ? 1 : 0) == 1 &&
                    EVP_CipherUpdate(context, payload.data(), &output_size, payload.data(), static_cast<int>(payload.size())) == 1 &&
                    EVP_CipherFinal_ex(context, payload.data() + output_size, &final_size) == 1;
    EVP_CIPHER_CTX_free(context);
    return ok && static_cast<size_t>(output_size + final_size) == payload.size();
}

int main() {
    std::mt19937 generator(20261115);
    std::uniform_int_distribution<int> byte(0, 255);
    int cases = 0, mismatches = 0;
    for (int round = 0; round < 2000; ++round) {
        std::uint8_t key[16], iv[16];
        for (auto& b : key) b = static_cast<std::uint8_t>(byte(generator));
        // The engine expands a 4-byte seed into the IV; any IV is tested here.
        for (auto& b : iv) b = static_cast<std::uint8_t>(byte(generator));
        const std::size_t length = static_cast<std::size_t>(round % 1500);
        std::vector<std::uint8_t> plain(length);
        for (auto& b : plain) b = static_cast<std::uint8_t>(byte(generator));
        for (bool encrypt : {true, false}) {
            auto a = plain, b = plain;
            const bool ok_ossl = OpenSslCfb(a, key, iv, encrypt);
            const bool ok_cng = Ps4Runtime::Cng::Aes128Cfb128(b.data(), b.size(), key, iv, encrypt);
            ++cases;
            if (!ok_ossl || !ok_cng || a != b) ++mismatches;
        }
        std::uint8_t mac_ossl[EVP_MAX_MD_SIZE]{}, mac_cng[20]{};
        unsigned int size = 0;
        const std::size_t message = static_cast<std::size_t>(round % 300);
        HMAC(EVP_sha1(), key, 16, plain.data(), message, mac_ossl, &size);
        const bool ok = Ps4Runtime::Cng::HmacSha1(key, 16, plain.data(), message, mac_cng);
        ++cases;
        if (!ok || size != 20 || std::memcmp(mac_ossl, mac_cng, 20) != 0) ++mismatches;
        std::uint8_t other[4] = {plain.empty() ? std::uint8_t(0) : plain[0], 1, 2, 3};
        std::uint8_t same[4] = {other[0], 1, 2, 3};
        ++cases;
        if ((CRYPTO_memcmp(other, same, 4) == 0) != Ps4Runtime::Cng::ConstantTimeEqual(other, same, 4)) ++mismatches;
    }
    std::printf("cases=%d mismatches=%d\n", cases, mismatches);
    return mismatches ? 1 : 0;
}
