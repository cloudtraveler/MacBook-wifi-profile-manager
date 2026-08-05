#!/usr/bin/env python3
"""AppIcon.icns 생성 (PNG 임베드 방식 ICNS — iconutil 없이 순수 파이썬)"""
import io
import struct
import math
from PIL import Image, ImageDraw

# ICNS 타입코드: (OSType, 픽셀크기)
ICNS_TYPES = [
    (b"icp4", 16), (b"icp5", 32), (b"icp6", 64),
    (b"ic07", 128), (b"ic08", 256), (b"ic09", 512),
    (b"ic10", 1024), (b"ic11", 32), (b"ic12", 64),
    (b"ic13", 256), (b"ic14", 512),
]

BG_TOP = (40, 96, 214)
BG_BOTTOM = (16, 44, 122)
ARC = (255, 255, 255)


def rounded_mask(size, radius_ratio=0.225):
    mask = Image.new("L", (size * 4, size * 4), 0)
    d = ImageDraw.Draw(mask)
    r = int(size * 4 * radius_ratio)
    d.rounded_rectangle([0, 0, size * 4 - 1, size * 4 - 1], radius=r, fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def render(size):
    s = max(size, 256)          # 큰 캔버스에 그린 뒤 축소 → 안티에일리어싱
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    grad = Image.new("RGBA", (s, s))
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        t = y / float(s - 1)
        gd.line([(0, y), (s, y)],
                fill=(int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
                      int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
                      int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t), 255))
    img.paste(grad, (0, 0))
    img.putalpha(rounded_mask(s))

    d = ImageDraw.Draw(img)
    cx, cy = s / 2.0, s * 0.72          # 신호 원점
    # Wi-Fi 호 3개
    for i, rad in enumerate((0.20, 0.32, 0.44)):
        r = s * rad
        w = s * 0.058
        d.arc([cx - r, cy - r, cx + r, cy + r], start=218, end=322,
              fill=ARC, width=int(w))
    # 중앙 점
    dot = s * 0.052
    d.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill=ARC)

    if size != s:
        img = img.resize((size, size), Image.LANCZOS)
    return img


def png_bytes(size):
    buf = io.BytesIO()
    render(size).save(buf, format="PNG")
    return buf.getvalue()


def build_icns(path):
    cache = {}
    entries = []
    for ostype, px in ICNS_TYPES:
        if px not in cache:
            cache[px] = png_bytes(px)
        data = cache[px]
        entries.append(ostype + struct.pack(">I", len(data) + 8) + data)
    body = b"".join(entries)
    with open(path, "wb") as fp:
        fp.write(b"icns" + struct.pack(">I", len(body) + 8) + body)
    return len(body) + 8


if __name__ == "__main__":
    n = build_icns("AppIcon.icns")
    render(512).save("icon_preview.png")
    print("AppIcon.icns 생성 완료 (%d bytes)" % n)
