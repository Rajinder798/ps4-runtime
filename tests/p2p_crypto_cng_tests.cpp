// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

// Known-answer tests for the CNG primitives used by the release-no-libressl engine
// variant: NIST SP 800-38A F.3.13 (CFB128-AES128) and RFC 2202 (HMAC-SHA1), plus
// every partial length, in-place round trips and the constant-time compare.
#include "p2p_crypto_cng.h"

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace {

int failures = 0;

void Check(bool condition, const char* what) {
    if (!condition) {
        std::printf("FAIL: %s\n", what);
        ++failures;
    }
}

std::vector<std::uint8_t> Hex(const char* text) {
    std::vector<std::uint8_t> bytes;
    for (std::size_t i = 0; text[i] && text[i + 1]; i += 2) {
        bytes.push_back(static_cast<std::uint8_t>(std::stoul(std::string(text + i, 2), nullptr, 16)));
    }
    return bytes;
}

template <std::size_t N>
void Copy(std::uint8_t (&out)[N], const std::vector<std::uint8_t>& in) {
    std::memcpy(out, in.data(), N);
}

} // namespace

int main() {
    using namespace Ps4Runtime::Cng;
    std::uint8_t key[16], iv[16];
    Copy(key, Hex("2b7e151628aed2a6abf7158809cf4f3c"));
    Copy(iv, Hex("000102030405060708090a0b0c0d0e0f"));
    const auto plain = Hex("6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51"
                           "30c81c46a35ce411e5fbc1191a0a52eff69f2445df4f9b17ad2b417be66c3710");
    const auto cipher = Hex("3b3fd92eb72dad20333449f8e83cfb4ac8a64537a0b3a93fcde3cdad9f1ce58b"
                            "26751f67a3cbb140b1808cf187a4f4dfc04b05357c5d1c0eeac4c66f9ff7f2e6");

    auto data = plain;
    Check(Aes128Cfb128(data.data(), data.size(), key, iv, true) && data == cipher, "NIST CFB128 encrypt");
    Check(Aes128Cfb128(data.data(), data.size(), key, iv, false) && data == plain, "NIST CFB128 decrypt");
    // CFB is a stream mode: every prefix encrypts to the same prefix of the ciphertext.
    for (std::size_t length = 0; length <= plain.size(); ++length) {
        std::vector<std::uint8_t> part(plain.begin(), plain.begin() + static_cast<std::ptrdiff_t>(length));
        const bool encrypted = Aes128Cfb128(part.data(), part.size(), key, iv, true) &&
                               std::equal(part.begin(), part.end(), cipher.begin());
        const bool decrypted = Aes128Cfb128(part.data(), part.size(), key, iv, false) &&
                               std::equal(part.begin(), part.end(), plain.begin());
        if (!encrypted || !decrypted) {
            std::printf("FAIL: CFB128 prefix length %zu\n", length);
            ++failures;
        }
    }
    std::uint8_t other_iv[16];
    Copy(other_iv, Hex("0f0e0d0c0b0a09080706050403020100"));
    data = plain;
    Check(Aes128Cfb128(data.data(), data.size(), key, other_iv, true) && data != cipher, "IV changes the output");

    struct Mac {
        std::vector<std::uint8_t> key;
        std::string message;
        const char* digest;
    };
    const Mac macs[] = {
        {std::vector<std::uint8_t>(20, 0x0b), "Hi There", "b617318655057264e28bc0b6fb378c8ef146be00"},
        {Hex("4a656665"), "what do ya want for nothing?", "effcdf6ae5eb2fa2d27416d5f184df9c259a7c79"},
        {std::vector<std::uint8_t>(80, 0xaa), "Test Using Larger Than Block-Size Key - Hash Key First",
         "aa4ae5e15272d00e95705637ce8a3b55ed402112"},
        // Empty message with a 16-byte key, as DeriveCommunicationId uses it.
        {Hex("000102030405060708090a0b0c0d0e0f"), "", "5433122f77bcf8a4d9b874b4149823ef5b7c207e"},
    };
    for (const auto& mac : macs) {
        std::uint8_t out[Sha1Size]{};
        const bool ok = HmacSha1(mac.key.data(), mac.key.size(),
                                 reinterpret_cast<const std::uint8_t*>(mac.message.data()), mac.message.size(), out);
        if (!ok || std::vector<std::uint8_t>(out, out + Sha1Size) != Hex(mac.digest)) {
            std::printf("FAIL: HMAC-SHA1 for message \"%s\"\n", mac.message.c_str());
            ++failures;
        }
    }

    std::uint8_t first[32]{}, second[32]{};
    Check(Random(first, sizeof(first)) && Random(second, sizeof(second)) && std::memcmp(first, second, 32) != 0,
          "random bytes differ between calls");
    std::uint8_t a[4] = {1, 2, 3, 4}, b[4] = {1, 2, 3, 4}, c[4] = {1, 2, 3, 5};
    Check(ConstantTimeEqual(a, b, 4), "equal buffers compare equal");
    Check(!ConstantTimeEqual(a, c, 4), "last-byte difference is detected");
    Check(ConstantTimeEqual(a, c, 0), "zero-length compare is equal");

    std::printf("%s (%d failures)\n", failures ? "FAILED" : "passed", failures);
    return failures ? 1 : 0;
}
