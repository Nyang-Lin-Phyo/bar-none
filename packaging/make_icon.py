#!/usr/bin/env python3
"""Regenerate assets/icon.ico and assets/icon.png from the artwork.

Pure standard library — no Pillow, no ImageMagick, nothing to install:

    python packaging/make_icon.py

Pipeline: decode assets/B N.png (8-bit RGBA), knock the white background
to transparent, area-average downscale to the standard icon sizes, then
write a multi-size .ico (BGRA + AND mask) and a 256 px window PNG.
"""

from __future__ import annotations

import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "assets", "B N.png")
ICO_OUT = os.path.join(ROOT, "assets", "icon.ico")
PNG_OUT = os.path.join(ROOT, "assets", "icon.png")

SIZES = (256, 128, 64, 48, 32, 16)
# Min RGB channel values that count as "white background": >= HI becomes
# fully transparent, LO..HI ramps down (kills the halo, keeps the art).
WHITE_LO, WHITE_HI = 245, 250


# ---------------------------------------------------------------- decoding

def read_png(path: str) -> tuple[int, int, bytearray]:
    """Decode a non-interlaced 8-bit RGB/RGBA PNG into RGBA pixels."""
    with open(path, "rb") as handle:
        data = handle.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"{path} is not a PNG")

    width = height = None
    bitdepth = colortype = interlace = None
    idat = bytearray()
    pos = 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length  # length + type + data + crc
        if ctype == b"IHDR":
            width, height, bitdepth, colortype, _, _, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
        elif ctype == b"IDAT":
            idat.extend(chunk)
        elif ctype == b"IEND":
            break
    if width is None:
        raise SystemExit("missing IHDR chunk")
    if bitdepth != 8 or colortype not in (2, 6) or interlace != 0:
        raise SystemExit(
            f"unsupported PNG: bitdepth={bitdepth} colortype={colortype} "
            f"interlace={interlace}"
        )

    channels = 4 if colortype == 6 else 3
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    pixels = bytearray(width * height * 4)
    previous = bytearray(stride)
    i = 0
    for y in range(height):
        filter_type = raw[i]
        i += 1
        line = bytearray(raw[i : i + stride])
        i += stride
        if filter_type == 1:  # Sub
            for x in range(channels, stride):
                line[x] = (line[x] + line[x - channels]) & 0xFF
        elif filter_type == 2:  # Up
            for x in range(stride):
                line[x] = (line[x] + previous[x]) & 0xFF
        elif filter_type == 3:  # Average
            for x in range(stride):
                left = line[x - channels] if x >= channels else 0
                line[x] = (line[x] + ((left + previous[x]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for x in range(stride):
                left = line[x - channels] if x >= channels else 0
                up = previous[x]
                upleft = previous[x - channels] if x >= channels else 0
                p = left + up - upleft
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upleft)
                if pa <= pb and pa <= pc:
                    predictor = left
                elif pb <= pc:
                    predictor = up
                else:
                    predictor = upleft
                line[x] = (line[x] + predictor) & 0xFF
        elif filter_type != 0:
            raise SystemExit(f"unknown PNG filter {filter_type}")

        offset = y * width * 4
        if channels == 4:
            pixels[offset : offset + stride] = line
        else:
            for x in range(width):
                o, s = offset + x * 4, x * 3
                pixels[o : o + 3] = line[s : s + 3]
                pixels[o + 3] = 255
        previous = line
    return width, height, pixels


# ------------------------------------------------------------ transparent

def knock_out_white(pixels: bytearray) -> None:
    """Make the white background transparent, in place."""
    lo, hi = WHITE_LO, WHITE_HI
    for offset in range(0, len(pixels), 4):
        r, g, b = pixels[offset], pixels[offset + 1], pixels[offset + 2]
        smallest = r if r < g else g
        if b < smallest:
            smallest = b
        if smallest >= hi:
            pixels[offset + 3] = 0
        elif smallest > lo:
            alpha = (hi - smallest) * 255 // (hi - lo)
            if alpha < pixels[offset + 3]:
                pixels[offset + 3] = alpha


# ---------------------------------------------------------------- scaling

def resize(
    pixels: bytearray, width: int, height: int, dst_w: int, dst_h: int
) -> bytearray:
    """Area-average (box filter) downscale with premultiplied alpha."""
    out = bytearray(dst_w * dst_h * 4)
    for dy in range(dst_h):
        y0 = int(dy * height / dst_h)
        y1 = max(int((dy + 1) * height / dst_h), y0 + 1)
        for dx in range(dst_w):
            x0 = int(dx * width / dst_w)
            x1 = max(int((dx + 1) * width / dst_w), x0 + 1)
            ra = ga = ba = sa = count = 0
            for y in range(y0, y1):
                base = y * width * 4
                for x in range(x0, x1):
                    o = base + x * 4
                    a = pixels[o + 3]
                    ra += pixels[o] * a
                    ga += pixels[o + 1] * a
                    ba += pixels[o + 2] * a
                    sa += a
                    count += 1
            o = (dy * dst_w + dx) * 4
            if sa:
                out[o] = ra // sa
                out[o + 1] = ga // sa
                out[o + 2] = ba // sa
            else:  # fully transparent: keep white so later rescales stay clean
                out[o] = out[o + 1] = out[o + 2] = 255
            out[o + 3] = sa // count
    return out


# ---------------------------------------------------------------- writing

def write_png(path: str, width: int, height: int, pixels: bytearray) -> None:
    def chunk(ctype: bytes, payload: bytes) -> bytes:
        body = ctype + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: None
        raw.extend(pixels[y * stride : (y + 1) * stride])

    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n")
        handle.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)))
        handle.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        handle.write(chunk(b"IEND", b""))


def write_ico(path: str, images: list[tuple[int, bytearray]]) -> None:
    """Multi-size ICO: BMP entries (BGRA, bottom-up) + empty AND mask."""
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    entries = b""
    blobs = b""
    offset = 6 + 16 * count
    for size, pixels in images:
        info = struct.pack(
            "<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0
        )
        xor = bytearray()
        for y in range(size - 1, -1, -1):  # bottom-up
            row = pixels[y * size * 4 : (y + 1) * size * 4]
            for x in range(size):
                o = x * 4
                xor += bytes((row[o + 2], row[o + 1], row[o], row[o + 3]))
        and_stride = ((size + 31) // 32) * 4
        and_mask = bytes(and_stride * size)  # all visible: alpha rules
        blob = info + bytes(xor) + and_mask
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,
            size if size < 256 else 0,
            0,
            0,
            1,
            32,
            len(blob),
            offset,
        )
        blobs += blob
        offset += len(blob)

    with open(path, "wb") as handle:
        handle.write(header + entries + blobs)


# ------------------------------------------------------------------ main

def main() -> None:
    width, height, pixels = read_png(SOURCE)
    if width != height:
        raise SystemExit(f"artwork must be square, got {width}x{height}")
    knock_out_white(pixels)

    images: list[tuple[int, bytearray]] = []
    current_w, current_h, current = width, height, pixels
    for size in SIZES:
        current = resize(current, current_w, current_h, size, size)
        current_w = current_h = size
        images.append((size, current))

    os.makedirs(os.path.dirname(PNG_OUT), exist_ok=True)
    write_png(PNG_OUT, 256, 256, images[0][1])
    write_ico(ICO_OUT, images)
    print(f"wrote {ICO_OUT}  (sizes: {', '.join(str(s) for s, _ in images)})")
    print(f"wrote {PNG_OUT}  (256 px window icon)")


if __name__ == "__main__":
    main()
