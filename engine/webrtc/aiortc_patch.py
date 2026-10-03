"""Receiver-side instrumentation (and two fixes) for aiortc, applied by monkeypatching from this module only.
The installed aiortc package is not edited.

1. Per-frame timestamps. A JitterBuffer subclass stamps, for every encoded frame it hands to the decoder,
   the wall clock of its first and of its last RTP packet (t_first, t_complete) and its packet count; a
   decoder wrapper stamps decode start / end. Stamps are keyed by the frame's (mapped) RTP timestamp,
   which aiortc also uses as the decoded av.VideoFrame's pts, so the reader can join them.

2. Frame completion on the RTP marker bit (use_marker=True, default). Stock aiortc only releases a video
   frame when the FIRST packet of the NEXT frame arrives (jitterbuffer._remove_frame looks for a timestamp
   change), which adds one frame interval to every frame: 8.3 ms at 120 fps, 33 ms at 30 fps. libwebrtc's
   packet buffer completes a frame on its last packet (marker bit set, all packets since the first one
   present). With use_marker=False the stock behaviour is kept, for comparison.

3. Buffer capacity. Stock aiortc gives the video jitter buffer 128 packets; a 1080p keyframe can be a few
   hundred packets (1200-byte RTP payloads), which can never be assembled in 128 slots (the buffer drops it
   and asks for a new keyframe, which is just as large). Video capacity here: 1024 packets.

4. Loopback ICE (loopback_only=True): aioice never offers 127.0.0.1 as a host candidate; MediaMTX in
   engine/webrtc/mediamtx.yml listens on 127.0.0.1 only, so the receiver offers 127.0.0.1 only.
"""
from __future__ import annotations

import time

_STATE = {"applied": False}
STAMPS = {}          # mapped rtp timestamp -> dict(t_first, t_complete, n_packets, nbytes, t_dec0, t_dec1, n_out)
COUNTERS = {"marker": 0, "stock": 0, "decode_errors": 0, "decoded": 0}


def apply(use_marker=True, video_capacity=1024, loopback_only=True):
    if _STATE["applied"]:
        return
    import aioice.ice
    import aiortc.rtcrtpreceiver as rr
    from aiortc.jitterbuffer import JitterBuffer, JitterFrame
    from aiortc.utils import uint16_add

    class StampedJitterBuffer(JitterBuffer):
        def __init__(self, capacity, prefetch=0, is_video=False):
            if is_video:
                capacity = max(capacity, video_capacity)
            super().__init__(capacity, prefetch=prefetch, is_video=is_video)
            self._marker = bool(use_marker and is_video)
            self._first = {}

        def _on_marker(self, packet):
            """All packets from the buffer origin to this marker packet present, same timestamp -> frame."""
            if self._origin is None:
                return None
            n = uint16_add(packet.sequence_number, -self._origin) + 1
            if n <= 0 or n > self._capacity:
                return None
            parts = []
            for k in range(n):
                p = self._packets[(self._origin + k) % self._capacity]
                if p is None or p.timestamp != packet.timestamp:
                    return None
                parts.append(p._data)
            frame = JitterFrame(data=b"".join(parts), timestamp=packet.timestamp)
            frame.n_packets = n
            self.remove(n)
            return frame

        def add(self, packet):
            now = time.time()
            ts = packet.timestamp
            if ts not in self._first:
                self._first[ts] = now
                if len(self._first) > 512:
                    for k in list(self._first)[:256]:
                        del self._first[k]
            pli, frame = super().add(packet)
            if frame is not None:
                COUNTERS["stock"] += 1
            elif self._marker and packet.marker:
                frame = self._on_marker(packet)
                if frame is not None:
                    COUNTERS["marker"] += 1
            if frame is not None:
                frame.t_complete = now
                frame.t_first = self._first.get(frame.timestamp, now)
            return pli, frame

    class StampingDecoder:
        def __init__(self, inner):
            self.inner = inner

        def decode(self, ef):
            t0 = time.time()
            out = self.inner.decode(ef)
            t1 = time.time()
            if not out:
                COUNTERS["decode_errors"] += 1
            COUNTERS["decoded"] += len(out)
            STAMPS[ef.timestamp] = dict(t_first=getattr(ef, "t_first", None), t_complete=getattr(ef, "t_complete", None),
                                        n_packets=getattr(ef, "n_packets", None), nbytes=len(ef.data),
                                        t_dec0=t0, t_dec1=t1, n_out=len(out))
            if len(STAMPS) > 4096:
                for k in list(STAMPS)[:2048]:
                    STAMPS.pop(k, None)
            return out

    _get_decoder = rr.get_decoder
    rr.JitterBuffer = StampedJitterBuffer
    rr.get_decoder = lambda codec: StampingDecoder(_get_decoder(codec))
    if loopback_only:
        aioice.ice.get_host_addresses = lambda use_ipv4, use_ipv6: ["127.0.0.1"] if use_ipv4 else []
    _STATE.update(applied=True, use_marker=bool(use_marker), video_capacity=video_capacity,
                  loopback_only=bool(loopback_only))


def state():
    return dict(_STATE)
