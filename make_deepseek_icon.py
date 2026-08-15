#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek Agent Studio 图标生成器（纯 Python 标准库，无需 Pillow）

生成：
  assets/deepseek_agent_logo.png   256x256 品牌 Logo
  assets/deepseek_agent.ico        可嵌入 exe 的 ICO 图标
"""

import struct
import zlib
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ASSETS = BASE_DIR / "assets"
SIZE = 256


def hex_rgb(value: str):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def lerp_color(a, b, t: float):
    return tuple(int(a[i] + (b[i] - a[i]) * max(0.0, min(1.0, t))) for i in range(3))


def in_triangle(px: float, py: float, a, b, c) -> bool:
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1 = sign((px, py), a, b)
    d2 = sign((px, py), b, c)
    d3 = sign((px, py), c, a)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def dist_to_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = x1 + t * dx, y1 + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def write_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    rows = []
    stride = width * 4
    for y in range(height):
        start = y * stride
        rows.append(b"\x00" + bytes(pixels[start:start + stride]))

    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def write_ico(path: Path, png: bytes) -> None:
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entry + png)


def build_pixels() -> bytearray:
    px = bytearray(SIZE * SIZE * 4)

    bg_top = hex_rgb("#16213f")
    bg_bottom = hex_rgb("#0a0e1a")
    body_top = hex_rgb("#5c7cfa")
    body_bottom = hex_rgb("#2f5fe0")
    belly = hex_rgb("#7c9cff")
    fin = hex_rgb("#2f6df6")
    tail_top = hex_rgb("#4d6bfe")
    tail_bottom = hex_rgb("#22d3ee")
    white = (255, 255, 255)
    dark = (10, 14, 26)
    cyan = hex_rgb("#22d3ee")

    # 鲸鱼身体椭圆参数
    bx, by, brx, bry = 122.0, 146.0, 82.0, 56.0
    belly_y, belly_ry = 168.0, 38.0
    eye_x, eye_y, eye_r = 98.0, 130.0, 12.0
    pupil_x, pupil_y, pupil_r = 103.0, 134.0, 6.0

    for y in range(SIZE):
        for x in range(SIZE):
            t = (x + y) / (2.0 * SIZE)
            r, g, b = lerp_color(bg_top, bg_bottom, t)
            a = 255

            # 身体
            e = ((x - bx) / brx) ** 2 + ((y - by) / bry) ** 2
            if e <= 1.0:
                bt = (y - (by - bry)) / (2.0 * bry)
                r, g, b = lerp_color(body_top, body_bottom, bt)

            # 腹部高光
            e2 = ((x - bx) / (brx * 0.78)) ** 2 + ((y - belly_y) / belly_ry) ** 2
            if e2 <= 1.0:
                r, g, b = lerp_color((r, g, b), belly, 0.55)

            # 尾鳍
            tail_upper = ((186, 124), (254, 62), (246, 104))
            tail_lower = ((186, 160), (248, 180), (254, 224))
            if in_triangle(x + 0.5, y + 0.5, *tail_upper) or in_triangle(x + 0.5, y + 0.5, *tail_lower):
                tt = (y - 62) / (224 - 62)
                r, g, b = lerp_color(tail_top, tail_bottom, tt)

            # 背鳍
            if in_triangle(x + 0.5, y + 0.5, (86, 118), (122, 42), (142, 112)):
                r, g, b = fin

            # 眼睛
            ed = ((x - eye_x) ** 2 + (y - eye_y) ** 2) ** 0.5
            if ed <= eye_r:
                r, g, b = white
            pd = ((x - pupil_x) ** 2 + (y - pupil_y) ** 2) ** 0.5
            if pd <= pupil_r:
                r, g, b = dark

            # 右上数据节点
            node_x, node_y, node_r = 194.0, 52.0, 22.0
            nd = ((x - node_x) ** 2 + (y - node_y) ** 2) ** 0.5
            if nd <= node_r:
                r, g, b = cyan
            if nd <= 7.0:
                r, g, b = dark
            if dist_to_segment(x + 0.5, y + 0.5, 158, 104, 188, 56) <= 5.0:
                r, g, b = cyan
            if dist_to_segment(x + 0.5, y + 0.5, 202, 80, 232, 100) <= 5.0:
                r, g, b = cyan

            idx = (y * SIZE + x) * 4
            px[idx] = max(0, min(255, int(r)))
            px[idx + 1] = max(0, min(255, int(g)))
            px[idx + 2] = max(0, min(255, int(b)))
            px[idx + 3] = a
    return px


def main() -> None:
    px = build_pixels()
    png_path = ASSETS / "deepseek_agent_logo.png"
    ico_path = ASSETS / "deepseek_agent.ico"
    write_png(png_path, SIZE, SIZE, px)

    # 从刚生成的 PNG 读取字节，封装成 ICO。
    png_bytes = png_path.read_bytes()
    write_ico(ico_path, png_bytes)
    print(f"[OK] {png_path}")
    print(f"[OK] {ico_path}")


if __name__ == "__main__":
    main()
