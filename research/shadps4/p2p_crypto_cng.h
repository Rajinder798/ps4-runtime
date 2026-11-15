// SPDX-FileCopyrightText: 2026 Rajinder Singh
// SPDX-License-Identifier: GPL-2.0-or-later
// See LICENSE in the project root for the full license text.

// Windows CNG (bcrypt.dll) replacements for the four OpenSSL primitives that
// shadPS4's P2P payload protection uses: AES-128 in CFB128 mode, HMAC-SHA1,
// secure random bytes and a constant-time compare. Used only by the
// release-no-libressl engine variant, so that variant links no LibreSSL. CNG is a
// Windows system library. CFB128 is built from single-block AES-ECB encryption,
// so any payload length works exactly as with EVP_aes_128_cfb128.
#pragma once

#include <cstddef>
#include <cstdint>

#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <bcrypt.h>

#if defined(_MSC_VER)
#pragma comment(lib, "bcrypt.lib")
#endif

namespace Ps4Runtime::Cng {

namespace Detail {

inline bool Ok(NTSTATUS status) {
    return status >= 0;
}

class Algorithm {
public:
    Algorithm(const wchar_t* name, ULONG flags) {
        if (!Ok(BCryptOpenAlgorithmProvider(&handle, name, nullptr, flags))) {
            handle = nullptr;
        }
    }
    ~Algorithm() {
        if (handle) {
            BCryptCloseAlgorithmProvider(handle, 0);
        }
    }
    Algorithm(const Algorithm&) = delete;
    Algorithm& operator=(const Algorithm&) = delete;
    BCRYPT_ALG_HANDLE handle = nullptr;
};

class Key {
public:
    ~Key() {
        if (handle) {
            BCryptDestroyKey(handle);
        }
    }
    BCRYPT_KEY_HANDLE handle = nullptr;
};

class Hash {
public:
    ~Hash() {
        if (handle) {
            BCryptDestroyHash(handle);
        }
    }
    BCRYPT_HASH_HANDLE handle = nullptr;
};

} // namespace Detail

constexpr std::size_t AesBlockSize = 16;
constexpr std::size_t Sha1Size = 20;

// AES-128-CFB128 in place, identical to OpenSSL's EVP_aes_128_cfb128 for every length.
inline bool Aes128Cfb128(std::uint8_t* data, std::size_t size, const std::uint8_t (&key)[16],
                         const std::uint8_t (&iv)[16], bool encrypt) {
    Detail::Algorithm aes(BCRYPT_AES_ALGORITHM, 0);
    if (!aes.handle) {
        return false;
    }
    static const wchar_t ecb[] = BCRYPT_CHAIN_MODE_ECB;
    if (!Detail::Ok(BCryptSetProperty(aes.handle, BCRYPT_CHAINING_MODE,
                                      reinterpret_cast<PUCHAR>(const_cast<wchar_t*>(ecb)), sizeof(ecb), 0))) {
        return false;
    }
    Detail::Key handle;
    if (!Detail::Ok(BCryptGenerateSymmetricKey(aes.handle, &handle.handle, nullptr, 0,
                                               const_cast<PUCHAR>(key), 16, 0))) {
        return false;
    }
    std::uint8_t feedback[AesBlockSize];
    for (std::size_t i = 0; i < AesBlockSize; ++i) {
        feedback[i] = iv[i];
    }
    for (std::size_t offset = 0; offset < size; offset += AesBlockSize) {
        std::uint8_t stream[AesBlockSize];
        ULONG written = 0;
        if (!Detail::Ok(BCryptEncrypt(handle.handle, feedback, AesBlockSize, nullptr, nullptr, 0, stream,
                                      AesBlockSize, &written, 0)) ||
            written != AesBlockSize) {
            return false;
        }
        const std::size_t count = size - offset < AesBlockSize ? size - offset : AesBlockSize;
        for (std::size_t i = 0; i < count; ++i) {
            const std::uint8_t input = data[offset + i];
            data[offset + i] = static_cast<std::uint8_t>(input ^ stream[i]);
            // The next block's input is always the ciphertext.
            feedback[i] = encrypt ? data[offset + i] : input;
        }
    }
    return true;
}

// HMAC-SHA1 of data under key (any lengths, including an empty message).
inline bool HmacSha1(const std::uint8_t* key, std::size_t key_size, const std::uint8_t* data,
                     std::size_t size, std::uint8_t (&out)[Sha1Size]) {
    Detail::Algorithm sha1(BCRYPT_SHA1_ALGORITHM, BCRYPT_ALG_HANDLE_HMAC_FLAG);
    if (!sha1.handle) {
        return false;
    }
    Detail::Hash hash;
    if (!Detail::Ok(BCryptCreateHash(sha1.handle, &hash.handle, nullptr, 0, const_cast<PUCHAR>(key),
                                     static_cast<ULONG>(key_size), 0))) {
        return false;
    }
    if (size && !Detail::Ok(BCryptHashData(hash.handle, const_cast<PUCHAR>(data), static_cast<ULONG>(size), 0))) {
        return false;
    }
    return Detail::Ok(BCryptFinishHash(hash.handle, out, Sha1Size, 0));
}

inline bool Random(std::uint8_t* out, std::size_t size) {
    return Detail::Ok(BCryptGenRandom(nullptr, out, static_cast<ULONG>(size), BCRYPT_USE_SYSTEM_PREFERRED_RNG));
}

// Compares every byte, so the time taken does not depend on where a mismatch is.
inline bool ConstantTimeEqual(const std::uint8_t* a, const std::uint8_t* b, std::size_t size) {
    unsigned difference = 0;
    for (std::size_t i = 0; i < size; ++i) {
        difference |= static_cast<unsigned>(a[i] ^ b[i]);
    }
    return difference == 0;
}

} // namespace Ps4Runtime::Cng
