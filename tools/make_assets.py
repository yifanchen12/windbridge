from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

size = 512
image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)

draw.rounded_rectangle((24, 24, 488, 488), radius=122, fill="#155866", outline="#D8BA70", width=13)
draw.ellipse((102, 99, 410, 407), fill="#1F7180", outline="#86BDC0", width=5)

# Original wind current.
draw.arc((92, 118, 432, 365), start=196, end=338, fill="#FFF9E7", width=25)
draw.arc((135, 163, 411, 389), start=192, end=314, fill="#DCEFEB", width=15)
draw.arc((166, 207, 371, 390), start=193, end=301, fill="#D8BA70", width=12)

# Feather/leaf at the leading edge.
draw.polygon(((167, 308), (229, 127), (273, 157), (223, 326)), fill="#FFF9E7")
draw.line((193, 318, 249, 145), fill="#C9A85D", width=9)
for y, direction in ((177, -1), (208, 1), (239, -1), (270, 1)):
    x = int(249 - (y - 145) * 0.32)
    draw.line((x, y, x + 48 * direction, y - 18), fill="#C9A85D", width=7)

# Three drifting seeds.
for x, y in ((340, 129), (386, 191), (335, 239)):
    draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill="#FFF9E7")
    draw.line((x, y + 7, x - 8, y + 27), fill="#FFF9E7", width=4)

png = ASSETS / "app_icon.png"
ico = ASSETS / "app_icon.ico"
image.save(png)
image.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(png)
print(ico)
