"""Minimal fragmented-MP4 muxer for a single H.264 track (pure stdlib), so browsers can
play Lucy's camera through Media Source Extensions.

    init = init_segment(sps, pps, width, height)
    frag = fragment(seq, decode_time, duration, nal_units, keyframe)
"""
import struct

TIMESCALE = 90000


def box(kind, *payloads):
    data = b"".join(payloads)
    return struct.pack(">I", 8 + len(data)) + kind + data


def full_box(kind, version, flags, *payloads):
    return box(kind, struct.pack(">I", (version << 24) | flags), *payloads)


def split_nals(annexb):
    """Annex-B byte stream -> list of NAL unit payloads (start codes removed)."""
    out, i, n = [], 0, len(annexb)
    starts = []
    while True:
        j = annexb.find(b"\x00\x00\x01", i)
        if j < 0:
            break
        starts.append(j + 3)
        i = j + 3
    for k, s in enumerate(starts):
        e = starts[k + 1] - 3 if k + 1 < len(starts) else n
        nal = annexb[s:e]
        while nal.endswith(b"\x00"):          # trailing zero of a 4-byte start code
            nal = nal[:-1]
        if nal:
            out.append(nal)
    return out


def codec_string(sps):
    return "avc1.%02x%02x%02x" % (sps[1], sps[2], sps[3])


def init_segment(sps, pps, width, height):
    avcc = box(b"avcC", bytes([1, sps[1], sps[2], sps[3], 0xFF, 0xE1]),
               struct.pack(">H", len(sps)), sps, b"\x01", struct.pack(">H", len(pps)), pps)
    avc1 = box(b"avc1", b"\x00" * 6, struct.pack(">H", 1), b"\x00" * 16,
               struct.pack(">HH", width, height), struct.pack(">II", 0x00480000, 0x00480000),
               b"\x00" * 4, struct.pack(">H", 1), b"\x00" * 32, struct.pack(">Hh", 0x18, -1), avcc)
    stbl = box(b"stbl",
               full_box(b"stsd", 0, 0, struct.pack(">I", 1), avc1),
               full_box(b"stts", 0, 0, struct.pack(">I", 0)),
               full_box(b"stsc", 0, 0, struct.pack(">I", 0)),
               full_box(b"stsz", 0, 0, struct.pack(">II", 0, 0)),
               full_box(b"stco", 0, 0, struct.pack(">I", 0)))
    dinf = box(b"dinf", full_box(b"dref", 0, 0, struct.pack(">I", 1), full_box(b"url ", 0, 1)))
    minf = box(b"minf", full_box(b"vmhd", 0, 1, b"\x00" * 8), dinf, stbl)
    mdia = box(b"mdia",
               full_box(b"mdhd", 0, 0, struct.pack(">IIIIHH", 0, 0, TIMESCALE, 0, 0x55C4, 0)),
               full_box(b"hdlr", 0, 0, b"\x00" * 4, b"vide", b"\x00" * 12, b"Lucy\x00"),
               minf)
    matrix = struct.pack(">9I", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
    tkhd = full_box(b"tkhd", 0, 3, struct.pack(">IIIII", 0, 0, 1, 0, 0), b"\x00" * 8,
                    struct.pack(">HHHH", 0, 0, 0, 0), matrix, struct.pack(">II", width << 16, height << 16))
    trak = box(b"trak", tkhd, mdia)
    mvhd = full_box(b"mvhd", 0, 0, struct.pack(">IIII", 0, 0, TIMESCALE, 0),
                    struct.pack(">IH", 0x10000, 0x100), b"\x00" * 10, matrix, b"\x00" * 24,
                    struct.pack(">I", 2))
    mvex = box(b"mvex", full_box(b"trex", 0, 0, struct.pack(">IIIII", 1, 1, 0, 0, 0)))
    ftyp = box(b"ftyp", b"isom", struct.pack(">I", 0x200), b"isomiso6avc1mp41")
    return ftyp + box(b"moov", mvhd, trak, mvex)


def fragment(seq, decode_time, duration, nals, keyframe):
    """One sample per fragment. `nals` are NAL payloads (no start codes)."""
    sample = b"".join(struct.pack(">I", len(n)) + n for n in nals)
    flags = 0x02000000 if keyframe else 0x01010000
    trun_body = struct.pack(">IiIII", 1, 0, duration, len(sample), flags)   # data offset patched below
    traf = lambda trun: box(b"traf",
                            full_box(b"tfhd", 0, 0x020000, struct.pack(">I", 1)),      # default-base-is-moof
                            full_box(b"tfdt", 1, 0, struct.pack(">Q", decode_time)),
                            trun)
    trun = full_box(b"trun", 0, 0x000701, trun_body)
    moof = box(b"moof", full_box(b"mfhd", 0, 0, struct.pack(">I", seq)), traf(trun))
    # data offset = from start of moof to first sample byte (moof size + mdat header)
    trun_body = struct.pack(">IiIII", 1, len(moof) + 8, duration, len(sample), flags)
    trun = full_box(b"trun", 0, 0x000701, trun_body)
    moof = box(b"moof", full_box(b"mfhd", 0, 0, struct.pack(">I", seq)), traf(trun))
    return moof + box(b"mdat", sample)
