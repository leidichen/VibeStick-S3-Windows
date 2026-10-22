"""Turn the DeepSeek logo into the two LVGL ARGB8888 icons used by the device (40 px and 32 px, whale centred).

Input : assets/providers/deepseek/logo-whale.png  (the whale from logo-source.svg on a transparent background,
        rendered at high resolution; logo-whale.svg is the cropped vector)
Output: generated/vibe_stick_deepseek_icon.c

The logo is DeepSeek's trademark artwork supplied by the repository owner; check you may redistribute it before
publishing your own copy. Run:  python tools/make_deepseek_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BLUE = (77, 107, 254)  # #4D6BFE


def interior_mask(alpha: Image.Image) -> Image.Image:
    """255 where the logo has an enclosed hole (belly, eye): in the original artwork these show the white tile."""
    pad = 4  # a frame of background, so the flood reaches every outside corner
    solid = Image.new("L", (alpha.width + 2 * pad, alpha.height + 2 * pad), 0)
    solid.paste(alpha.point(lambda v: 255 if v > 127 else 0), (pad, pad))
    ImageDraw.floodfill(solid, (0, 0), 128)  # paints the background reachable from outside
    holes = solid.point(lambda v: 255 if v == 0 else 0)
    return holes.crop((pad, pad, pad + alpha.width, pad + alpha.height))


def icon(src: Image.Image, size: int) -> Image.Image:
    box = src.getchannel("A").getbbox()
    whale = src.crop(box)
    holes = interior_mask(whale.getchannel("A"))
    scale = (size - 2) / max(whale.size)  # 1 px margin
    w, h = max(1, round(whale.width * scale)), max(1, round(whale.height * scale))
    alpha = whale.getchannel("A").resize((w, h), Image.LANCZOS)  # resample only alpha: the colour is a constant
    white = holes.resize((w, h), Image.LANCZOS)
    pos = ((size - w) // 2, (size - h) // 2)
    out = Image.new("RGBA", (size, size), BLUE + (0,))
    out.paste(Image.new("RGBA", (w, h), (255, 255, 255, 255)), pos, white)   # white belly and eye first
    out.paste(Image.new("RGBA", (w, h), BLUE + (255,)), pos, alpha)         # blue body over it
    return out


def c_array(name: str, img: Image.Image) -> str:
    data = bytearray()
    for r, g, b, a in img.getdata():
        data += bytes((b, g, r, a))  # LV_COLOR_FORMAT_ARGB8888 is stored B, G, R, A
    rows = ["    " + ", ".join(f"0x{v:02x}" for v in data[i:i + 16]) + "," for i in range(0, len(data), 16)]
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
    src = Image.open(ROOT / "assets" / "providers" / "deepseek" / "logo-whale.png").convert("RGBA")
    parts = ['#include "vibe_stick_ui_assets.h"\n']
    preview = Image.new("RGBA", (100, 50), (14, 16, 20, 255))
    for i, size in enumerate((40, 32)):
        img = icon(src, size)
        parts.append(c_array(f"vibe_stick_provider_deepseek_icon_{size}", img))
        preview.paste(img, (5 + i * 50, 5), img)
    (ROOT / "generated" / "vibe_stick_deepseek_icon.c").write_text("\n".join(parts), encoding="utf-8", newline="\n")
    preview.resize((400, 200), Image.NEAREST).save(ROOT / "assets" / "providers" / "deepseek" / "preview.png")


if __name__ == "__main__":
    main()
