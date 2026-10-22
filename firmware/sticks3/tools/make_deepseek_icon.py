"""Draw the simple placeholder DeepSeek icon (a whale silhouette in brand blue) and emit LVGL ARGB8888 C data.

Not the official logo artwork: swap assets/providers/deepseek/icon-*.png for the real files if you have the right
to use them, then run this script again.
    python tools/make_deepseek_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BLUE = (77, 107, 254, 255)
SS = 8


def draw(size: int) -> Image.Image:
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 40.0

    def p(x, y):
        return (x * u, y * u)

    d.ellipse([*p(4, 14), *p(31, 34)], fill=BLUE)                                   # body
    d.polygon([p(28, 22), p(36, 12), p(38, 16), p(34, 22), p(38, 28), p(36, 32)], fill=BLUE)  # tail
    d.polygon([p(14, 16), p(10, 6), p(20, 14)], fill=BLUE)                          # back fin
    d.ellipse([*p(9, 21), *p(13, 25)], fill=(255, 255, 255, 255))                  # eye
    d.arc([*p(6, 24), *p(20, 32)], 20, 120, fill=(255, 255, 255, 255), width=int(1.2 * u))  # smile
    return img.resize((size, size), Image.LANCZOS)


def c_array(name: str, img: Image.Image) -> str:
    data = bytearray()
    for r, g, b, a in img.getdata():
        data += bytes((b, g, r, a))  # LV_COLOR_FORMAT_ARGB8888 is stored B, G, R, A
    rows = []
    for i in range(0, len(data), 16):
        rows.append("    " + ", ".join(f"0x{v:02x}" for v in data[i:i + 16]) + ",")
    size = img.width
    return (
        f"static const uint8_t {name}_data[] = {{\n" + "\n".join(rows) + "\n};\n\n"
        f"const lv_image_dsc_t {name} = {{\n"
        "    .header = {\n        .magic = LV_IMAGE_HEADER_MAGIC,\n        .cf = LV_COLOR_FORMAT_ARGB8888,\n"
        f"        .flags = 0,\n        .w = {size},\n        .h = {size},\n        .stride = {size * 4},\n"
        "        .reserved_2 = 0,\n    },\n"
        f"    .data_size = sizeof({name}_data),\n    .data = {name}_data,\n    .reserved = NULL,\n}};\n"
    )


def main() -> None:
    out_dir = ROOT / "assets" / "providers" / "deepseek"
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = ['#include "vibe_stick_ui_assets.h"\n']
    for size in (40, 32):
        png = out_dir / f"icon-{size}.png"
        img = Image.open(png).convert("RGBA") if png.exists() else draw(size)
        if not png.exists():
            img.save(png)
        if img.size != (size, size):
            img = img.resize((size, size), Image.LANCZOS)
        parts.append(c_array(f"vibe_stick_provider_deepseek_icon_{size}", img))
    (ROOT / "generated" / "vibe_stick_deepseek_icon.c").write_text("\n".join(parts), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
