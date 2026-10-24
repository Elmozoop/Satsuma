"""Regenerate assets/icon.png and assets/icon.ico (run from the project root)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024  # draw big, downsample for crisp small sizes
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# Fruit body with a soft radial-ish shade built from concentric circles
cx, cy, r = S * 0.46, S * 0.60, S * 0.37
for i in range(60, 0, -1):
    t = i / 60
    col = (int(255 - 25 * t), int(150 - 55 * t), int(40 - 25 * t), 255)
    rr = r * (0.55 + 0.45 * t)
    off = (1 - t) * S * 0.06
    d.ellipse([cx - rr - off, cy - rr - off, cx + rr - off, cy + rr - off], fill=col)
# crisp outer edge
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
body = Image.new("RGBA", (S, S), (0, 0, 0, 0))
body.paste(img, mask=mask)
img = body
d = ImageDraw.Draw(img)

# highlight
hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(hl).ellipse([cx - r * 0.55, cy - r * 0.70, cx - r * 0.05, cy - r * 0.30],
                           fill=(255, 255, 255, 70))
img = Image.alpha_composite(img, hl.filter(ImageFilter.GaussianBlur(S * 0.02)))
d = ImageDraw.Draw(img)

# stem dimple + leaf
d.ellipse([cx - S * 0.03, cy - r - S * 0.01, cx + S * 0.03, cy - r + S * 0.05], fill=(150, 80, 20, 255))
leaf = [(cx + S * 0.01, cy - r + S * 0.02), (cx + S * 0.10, cy - r - S * 0.16),
        (cx + S * 0.30, cy - r - S * 0.20), (cx + S * 0.40, cy - r - S * 0.12),
        (cx + S * 0.28, cy - r - S * 0.02), (cx + S * 0.12, cy - r + S * 0.03)]
d.polygon(leaf, fill=(78, 168, 70, 255))
d.line([(cx + S * 0.03, cy - r + S * 0.01), (cx + S * 0.32, cy - r - S * 0.13)],
       fill=(50, 120, 45, 255), width=int(S * 0.012))

out = Path("assets")
out.mkdir(exist_ok=True)
img.resize((256, 256), Image.LANCZOS).save(out / "icon.png")
img.save(out / "icon.ico", sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
                                  (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote", out / "icon.png", "and", out / "icon.ico")
