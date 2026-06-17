"""PPF pixel-font codec — matches firmware pixel_font.cpp exactly.

Header (big-endian), 46 bytes fixed:
  0-3   magic 'ppf!'
  4-5   u16 flags
  6-9   u32 glyph_count
  10-11 u16 glyph_width   (font-wide MAX width; drives fixed bytes-per-row)
  12-13 u16 glyph_height
  14-45 name, fixed 32 bytes, NUL-padded
Glyph records: glyph_count * (codepoint:u32, width:u16)   [6 bytes each]
Bitmap: glyph_count * (bpr * glyph_height) bytes, FIXED stride,
        bpr = (glyph_width + 7) // 8, row-major, MSB = leftmost pixel.
Each glyph's per-row data is left-justified into bpr bytes regardless of
its own (narrower) width.
"""
import struct

MAGIC = b'ppf!'

def decode(data):
    assert data[0:4] == MAGIC, "bad magic"
    flags = struct.unpack('>H', data[4:6])[0]
    count = struct.unpack('>I', data[6:10])[0]
    gwidth = struct.unpack('>H', data[10:12])[0]
    height = struct.unpack('>H', data[12:14])[0]
    name = data[14:46].split(b'\x00')[0].decode('latin-1')
    bpr = (gwidth + 7) // 8
    gsize = bpr * height
    recs = []
    pos = 46
    for _ in range(count):
        cp = struct.unpack('>I', data[pos:pos + 4])[0]
        w = struct.unpack('>H', data[pos + 4:pos + 6])[0]
        recs.append((cp, w))
        pos += 6
    bm = data[pos:]
    glyphs = []
    for gi, (cp, w) in enumerate(recs):
        base = gi * gsize
        rows = []
        for r in range(height):
            rowbytes = bm[base + r * bpr: base + r * bpr + bpr]
            row = [((rowbytes[c // 8] >> (7 - c % 8)) & 1) for c in range(w)]
            rows.append(row)
        glyphs.append((cp, w, rows))
    return {'flags': flags, 'name': name, 'glyph_width': gwidth,
            'height': height, 'glyphs': glyphs}

def encode(name, height, glyphs, flags=0, glyph_width=None):
    """glyphs: list of (cp, width, rows). glyph_width defaults to max width."""
    if glyph_width is None:
        glyph_width = max((w for (_, w, _) in glyphs), default=0)
    bpr = (glyph_width + 7) // 8
    out = bytearray()
    out += MAGIC
    out += struct.pack('>H', flags)
    out += struct.pack('>I', len(glyphs))
    out += struct.pack('>H', glyph_width)
    out += struct.pack('>H', height)
    nb = name.encode('latin-1')
    assert len(nb) <= 31, "name too long (max 31 + NUL in 32-byte field)"
    out += nb + b'\x00' * (32 - len(nb))
    for (cp, w, rows) in glyphs:
        out += struct.pack('>I', cp) + struct.pack('>H', w)
    for (cp, w, rows) in glyphs:
        for r in range(height):
            row = rows[r] if r < len(rows) else []
            for byte_i in range(bpr):
                b = 0
                for bit in range(8):
                    c = byte_i * 8 + bit
                    if c < w and c < len(row) and row[c]:
                        b |= (1 << (7 - bit))
                out.append(b)
    return bytes(out)
