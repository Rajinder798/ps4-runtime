# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Independent stereo tone/silence analysis for the pinned SDL disk sink."""
from array import array
import hashlib
import math
import sys

RATE = 48000
PERIODS = (64, 96, 128, 192)
WINDOW = 6144
MAX_PCM_BYTES = 16 * 1024 * 1024


def decode_capture(path, stderr):
    # Only SDL's own device-open message establishes the format; guest logs and
    # AudioOut return values do not. The runner supplies a fresh absolute path.
    wanted = f"Writing to file [{path}], format=F32LE channels=2 freq=48000."
    if wanted not in stderr or "You are using the SDL disk i/o audio driver!" not in stderr:
        raise ValueError("Missing exact SDL disk sink/format evidence")
    return decode_pcm(path)


def decode_pcm(path):
    """Bounded F32LE parser only; callers must establish source/format provenance."""
    if not path.is_file() or not 8 <= path.stat().st_size <= MAX_PCM_BYTES:
        raise ValueError("Missing or oversized SDL PCM output")
    data = path.read_bytes()
    if len(data) % 8:
        raise ValueError("Truncated stereo PCM frame")
    samples = array("f")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    if any(not math.isfinite(value) or abs(value) > 1 for value in samples):
        raise ValueError("Invalid PCM sample")
    return samples, hashlib.sha256(data).hexdigest()


def tone_fraction(values, frequency):
    # Goertzel projection at a known fundamental; amplitude/gain and phase are
    # independent of the guest's integer square-wave generator.
    coefficient = 2 * math.cos(2 * math.pi * frequency / RATE)
    previous = before = energy = 0.0
    for value in values:
        current = value + coefficient * previous - before
        before, previous = previous, current
        energy += value * value
    power = previous * previous + before * before - coefficient * previous * before
    return 0.0 if energy == 0 else 2 * power / (len(values) * energy)


def analyze(samples, challenge):
    if len(challenge) != 4 or set(challenge) != set(range(4)):
        raise ValueError("Invalid audio challenge")
    expected = [(RATE / PERIODS[challenge[i]], RATE / PERIODS[challenge[i+1]]) for i in (0, 2)]
    return _analyze_sequence(samples, expected, ("silence", "tone0", "tone1", "silence"), 12)


def analyze_interaction(samples, challenge):
    if len(challenge) != 4 or set(challenge) != set(range(4)):
        raise ValueError("Invalid audio challenge")
    expected = [(RATE / PERIODS[challenge[0]], RATE / PERIODS[challenge[1]])]
    # Input/screenshot handshakes hold each state for a variable duration.
    # The separate audio-pattern fixture retains its original 12-second bound.
    return _analyze_sequence(samples, expected, ("silence", "tone0", "silence"), 20)


def analyze_volume(samples, challenge, volume_percent):
    """Fixed interactive-av amplitude oracle; never infer gain from configuration."""
    if type(volume_percent) is not int or volume_percent not in (0, 50, 100):
        raise ValueError("Volume research supports only integer 0, 50 or 100 percent")
    if len(challenge) != 4 or set(challenge) != set(range(4)):
        raise ValueError("Invalid audio challenge")
    if (len(samples) % 2 or not RATE * 3 <= len(samples) // 2 <= RATE * 20 or
            any(not math.isfinite(x) or abs(x) > 1 for x in samples)):
        raise ValueError("Invalid or out-of-bounds volume PCM")
    peak = max(abs(x) for x in samples)
    if volume_percent == 0:
        if peak >= 0.00001:
            raise ValueError("Muted PCM contains non-silent samples")
        return dict(sample_rate=RATE, channels=2, sample_format="F32LE", frames=len(samples)//2,
                    volume_percent=0, muted=True, peak=peak, silence_peak_limit=0.00001,
                    tone_verified=False)
    result = analyze_interaction(samples, challenge)
    # The reviewed fixture emits an S16 square wave of +/-2000 on each channel.
    # Its RMS is its amplitude. No measured reference or fitted scale is used.
    expected = (2000 / 32768) * volume_percent / 100
    if peak > expected * 1.05:
        raise ValueError("PCM amplitude does not match requested volume")
    try:
        result = _analyze_sequence(samples, result["expected_tone_pairs_hz"],
            ("silence", "tone0", "silence"), 20, rms_range=(expected * 0.95, expected * 1.05))
    except ValueError as error:
        raise ValueError("PCM amplitude does not match requested volume") from error
    return dict(**result, volume_percent=volume_percent, muted=False, peak=peak,
                expected_rms=expected, relative_rms_tolerance=0.05, tone_verified=True)


def _analyze_sequence(samples, expected, kinds, maximum_seconds, *, rms_range=(0.005, 0.15)):
    if len(samples) % 2 or not RATE * 3 <= len(samples) // 2 <= RATE * maximum_seconds:
        raise ValueError("PCM frame count outside the bounded fixture range")
    windows = []
    for start in range(0, len(samples) // 2 - WINDOW + 1, WINDOW // 2):
        left, right = samples[2*start:2*(start+WINDOW):2], samples[2*start+1:2*(start+WINDOW):2]
        rms = [math.sqrt(sum(x*x for x in channel) / WINDOW) for channel in (left, right)]
        kind = "other"
        if max(rms) < 0.00001:
            kind = "silence"
        elif min(rms) >= rms_range[0] and max(rms) <= rms_range[1]:
            for phase, frequencies in enumerate(expected):
                if all(tone_fraction(channel, frequency) >= 0.65 for channel, frequency in zip((left,right), frequencies)):
                    kind = "tone" + str(phase)
                    break
        windows.append(dict(start_frame=start, kind=kind, rms=rms))
    # Four overlapping windows span 0.32 s. Require ordered sustained silence,
    # each channel-specific tone pair, then silence. A transient cannot pass.
    matched, cursor = [], 0
    for kind in kinds:
        found = False
        for index in range(cursor, len(windows) - 3):
            if all(window["kind"] == kind for window in windows[index:index+4]):
                selected = windows[index:index+4]
                matched.append(dict(kind=kind, start_frame=selected[0]["start_frame"],
                    end_frame=selected[-1]["start_frame"] + WINDOW,
                    rms_min=min(min(w["rms"]) for w in selected), rms_max=max(max(w["rms"]) for w in selected)))
                cursor, found = index + 4, True
                break
        if not found:
            raise ValueError("PCM does not contain the required ordered stereo tones and silence: " + kind)
    return dict(sample_rate=RATE, channels=2, sample_format="F32LE", frames=len(samples)//2,
                expected_tone_pairs_hz=expected, matched_windows=matched,
                window_frames=WINDOW, fundamental_energy_fraction_min=0.65)


def verify(path, stderr, challenge):
    samples, checksum = decode_capture(path, stderr)
    return dict(**analyze(samples, challenge), pcm_sha256=checksum)


def verify_interaction(path, stderr, challenge):
    samples, checksum = decode_capture(path, stderr)
    return dict(**analyze_interaction(samples, challenge), pcm_sha256=checksum)
