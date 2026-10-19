# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later

"""Strict live-guest state, repeated input and independent PCM qualification."""
import re
import struct

import audio_evidence as audio
import run_homebrew_startup as startup
import videoout_evidence as video

BEGIN = "live-av: begin"
READY = "live-av: ready running=1 audio_thread=1"
SAMPLE = re.compile(r"live-av: sample=([0-9]{1,3}) buttons=([0-9]{1,10}) "
                    r"timestamp=([0-9]{1,20}) flip=([0-9]{1,20}) audio_blocks=([0-9]{1,10})")


def progress(events):
    # Reuse only the strict engine-event validator. No hello_world marker or
    # finite-fixture PASS grants completion to this continuously running guest.
    strict = startup.evaluate(events)
    entered = begun = ready = False
    samples = []
    for event in events:
        if event["event"] == "guest_entry":
            entered = True
        if event["event"] != "guest_output":
            continue
        text = event["text"]
        if text == BEGIN:
            if not entered or begun:
                raise ValueError("Live begin without unique strict guest entry")
            begun = True
        elif text == READY:
            if not begun or ready:
                raise ValueError("Live readiness without unique begin")
            ready = True
        elif text.startswith("live-av:"):
            match = SAMPLE.fullmatch(text)
            if not ready or match is None:
                raise ValueError("Invalid/failing live guest output: " + text)
            sequence, buttons, timestamp, flip, blocks = map(int, match.groups())
            if (sequence != len(samples) or sequence >= 128 or buttons > 0xffffffff or
                    not 0 < timestamp <= 0xffffffffffffffff or not 0 < flip <= 0xffffffffffffffff or
                    blocks > 0xffffffff or (samples and
                    (timestamp <= samples[-1]["timestamp"] or flip <= samples[-1]["flip"] or
                     blocks < samples[-1]["audio_blocks"] or buttons == samples[-1]["buttons"]))):
                raise ValueError("Non-monotonic/duplicate live guest observation")
            samples.append(dict(sequence=sequence, buttons=buttons, timestamp=timestamp,
                                flip=flip, audio_blocks=blocks, elapsed_us=event["elapsed_us"]))
    return dict(guest_entry_observed=strict["guest_entry_observed"], running_observed=ready and bool(samples),
                guest_completed=False, samples=samples)


def verify_input(path, samples, captures):
    if not path.is_file() or path.stat().st_size != len(samples) * 24 or not 5 <= len(samples) <= 128:
        raise ValueError("Missing/wrong-size live guest input records")
    records = list(struct.iter_unpack("<IIQQ", path.read_bytes()))
    expected = [(s["sequence"], s["buttons"], s["timestamp"], s["flip"]) for s in samples]
    if records != expected:
        raise ValueError("Live guest file and strict output disagree")
    transitions = []
    for sample in samples:
        pressed = bool(sample["buttons"] & 0x4000)
        if not transitions or pressed != bool(transitions[-1]["buttons"] & 0x4000):
            transitions.append(sample)
    if ([bool(s["buttons"] & 0x4000) for s in transitions[:5]] != [False, True, False, True, False] or
            samples[-1]["audio_blocks"] <= samples[0]["audio_blocks"]):
        raise ValueError("Live input does not establish two independent Cross cycles with active audio")
    qualified = {c["sequence"]: c for c in captures}
    for sample in transitions:
        capture = qualified.get(sample["sequence"])
        if capture is None or capture["image_phase"] != int(bool(sample["buttons"] & 0x4000)):
            raise ValueError("Missing independently checked live Vulkan state")
    return dict(two_cycles_verified=True, transitions=transitions,
                pressed_at_close=bool(samples[-1]["buttons"] & 0x4000),
                observations_sha256=startup.digest(path))


def expected_pixels(palette, sequence, buttons):
    if type(sequence) is not int or not 0 <= sequence < 128 or type(buttons) is not int or not 0 <= buttons <= 0xffffffff:
        raise ValueError("Invalid live image identity")
    pixels = bytearray(video.expected_pixels(palette, int(bool(buttons & 0x4000))))
    for bit in range(8):
        pixels[bit * 4:bit * 4 + 4] = bytes([255 if sequence & (1 << bit) else 0] * 3 + [255])
    return bytes(pixels)


def verify_image(path, palette, sequence, buttons):
    if not path.is_file() or not 0 < path.stat().st_size <= video.MAX_PNG_BYTES:
        raise ValueError("Missing/oversized live PNG")
    if video.decode_png(path.read_bytes()) != expected_pixels(palette, sequence, buttons):
        raise video.CaptureMismatch("Live pixels do not match the exact guest observation/challenge")
    return dict(sequence=sequence, buttons=buttons, image_phase=int(bool(buttons & 0x4000)),
                pixels_verified=video.WIDTH * video.HEIGHT, sha256=startup.digest(path))


def analyze_audio(samples, challenge, pressed_at_close):
    if len(challenge) != 4 or set(challenge) != set(range(4)) or type(pressed_at_close) is not bool:
        raise ValueError("Invalid live audio challenge/state")
    expected = [(audio.RATE / audio.PERIODS[challenge[0]], audio.RATE / audio.PERIODS[challenge[1]])]
    kinds = ("silence", "tone0", "silence", "tone0", "silence")
    if pressed_at_close:
        kinds += ("tone0",)
    amplitude = 2000 / 32768
    return audio._analyze_sequence(samples, expected, kinds, 30,
                                   rms_range=(amplitude * 0.95, amplitude * 1.05))
