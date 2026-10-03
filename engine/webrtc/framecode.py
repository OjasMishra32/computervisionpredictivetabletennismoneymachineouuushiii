"""Frame identity carried inside the video itself: a binary code strip appended BELOW the picture.

The sender adds STRIP_H rows under the 1080-row picture (1920x1080 -> 1920x1136, both multiples of 16 so
the code sits in its own macroblock rows): 8 grey filler rows, then 3 code rows of 16 px, 32 cells each
(60 px wide at 1920). A cell is luma 235 (bit 1) or 16 (bit 0), chroma neutral. The receiver reads the
cells back (mean of the inner half of each cell, threshold 128) and crops the strip off before the
detector, so the picture the detector sees is the codec's reconstruction of the original 1080 rows and
nothing else (the code is never drawn over the image).

Payload (96 bits): seq (24) | flags (8) | source frame (16) | crc16 (16) | capture time, ms mod 2^32 (32)
  seq          send sequence number (every frame the sender emits: lead-in, clip, trailer)
  flags        LEADIN / CLIP / END
  src          OpenTTGames source frame number (test_2: 2000..2999); 0xFFFF for lead-in / trailer
  t_capture    wall clock (time.time() * 1000, mod 2^32) at which the frame was due at the virtual camera;
               lets a receiver on the same clock compute latency without the sender's log
  crc16        CRC-CCITT over the other 80 bits: a frame whose code does not check is reported, not guessed
"""
from __future__ import annotations

import binascii
import struct

import numpy as np

FILL_H = 8          # grey rows between the picture and the code (keeps deblocking off the picture edge)
ROW_H = 16
ROWS = 3
CELLS = 32
STRIP_H = FILL_H + ROWS * ROW_H      # 56: 1080 + 56 = 1136 = 71 macroblock rows
Y1, Y0, NEUTRAL = 235, 16, 128

LEADIN, CLIP, END = 1, 2, 4
NO_SRC = 0xFFFF


def _pack(seq, flags, src, t_ms):
    body = struct.pack(">I", ((seq & 0xFFFFFF) << 8) | (flags & 0xFF)) + struct.pack(">H", src & 0xFFFF)
    tail = struct.pack(">I", t_ms & 0xFFFFFFFF)
    crc = binascii.crc_hqx(body + tail, 0xFFFF)
    return body + struct.pack(">H", crc) + tail          # 12 bytes = 96 bits


def bits_for(seq, flags, src, t_ms):
    b = np.frombuffer(_pack(seq, flags, src, t_ms), np.uint8)
    return np.unpackbits(b).reshape(ROWS, CELLS)


def draw(y_strip, seq, flags, src, t_ms):
    """y_strip: luma rows [STRIP_H, W] (a view into the frame buffer), written in place."""
    w = y_strip.shape[1]
    cw = w // CELLS
    bits = bits_for(seq, flags, src, t_ms)
    y_strip[:FILL_H] = NEUTRAL
    for r in range(ROWS):
        row = np.repeat(np.where(bits[r] > 0, Y1, Y0).astype(np.uint8), cw)
        rr = y_strip[FILL_H + r * ROW_H: FILL_H + (r + 1) * ROW_H]
        rr[:, :CELLS * cw] = row
        rr[:, CELLS * cw:] = NEUTRAL


def read(y_strip):
    """-> dict(seq, flags, src, t_ms) or None if the CRC does not check."""
    w = y_strip.shape[1]
    cw = w // CELLS
    m0, m1 = cw // 4, cw - cw // 4
    v0, v1 = ROW_H // 4, ROW_H - ROW_H // 4
    bits = np.empty((ROWS, CELLS), np.uint8)
    for r in range(ROWS):
        band = y_strip[FILL_H + r * ROW_H + v0: FILL_H + r * ROW_H + v1, :CELLS * cw].astype(np.float32)
        cells = band.reshape(band.shape[0], CELLS, cw)[:, :, m0:m1].mean(axis=(0, 2))
        bits[r] = cells > 128
    raw = np.packbits(bits.ravel()).tobytes()
    head, src, crc, tail = raw[:4], raw[4:6], raw[6:8], raw[8:12]
    if binascii.crc_hqx(head + src + tail, 0xFFFF) != struct.unpack(">H", crc)[0]:
        return None
    hv = struct.unpack(">I", head)[0]
    return dict(seq=hv >> 8, flags=hv & 0xFF, src=struct.unpack(">H", src)[0], t_ms=struct.unpack(">I", tail)[0])


def unwrap_ms(t_ms_mod, t_ref_s):
    """Full epoch seconds from a capture time mod 2^32 ms, given a nearby wall clock (same host / synced)."""
    ref = int(round(t_ref_s * 1000))
    base = ref - (ref % (1 << 32))
    cands = [base + t_ms_mod + k * (1 << 32) for k in (-1, 0, 1)]
    return min(cands, key=lambda c: abs(c - ref)) / 1000.0
