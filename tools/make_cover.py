"""Erzeugt ein schlichtes Cover (1400x1400 JPG) unter docs/cover.jpg."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 1400
img = Image.new("RGB", (S, S), "#14213d")
d = ImageDraw.Draw(img)
d.rectangle([90, 90, S - 90, S - 90], outline="#fca311", width=10)


def font(size):
    for p in ["/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


d.text((S // 2, 600), "Daily", font=font(280), fill="#ffffff", anchor="mm")
d.text((S // 2, 880), "Briefing", font=font(280), fill="#fca311", anchor="mm")
d.text((S // 2, 1150), "Nachrichten · Wirtschaft · AI", font=font(64), fill="#e5e5e5", anchor="mm")
out = Path(__file__).resolve().parent.parent / "docs" / "cover.jpg"
img.save(out, quality=88)
print(out)
