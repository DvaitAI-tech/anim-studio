"""Generate a Skill45 end-card PNG (1280x720) for the Ram & Riya story outro."""
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "endcard.png")

# Skill45 blue gradient background
img = Image.new("RGB", (W, H), (16, 70, 150))
top, bot = (20, 90, 200), (8, 40, 95)
px = img.load()
for y in range(H):
    t = y / H
    px_row = tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3))
    for x in range(W):
        px[x, y] = px_row
d = ImageDraw.Draw(img)

def font(sz, bold=True):
    for f in ([r"C:\Windows\Fonts\arialbd.ttf"] if bold else [r"C:\Windows\Fonts\arial.ttf"]):
        if os.path.exists(f):
            return ImageFont.truetype(f, sz)
    return ImageFont.load_default()

def center(text, y, fnt, fill):
    bb = d.textbbox((0, 0), text, font=fnt)
    d.text(((W - (bb[2] - bb[0])) / 2, y), text, font=fnt, fill=fill)

center("Skill45", 200, font(150), (255, 255, 255))
center("Learn one new skill a day", 380, font(48, False), (210, 230, 255))
# URL pill
url = "skill45.vercel.app"
fu = font(46)
bb = d.textbbox((0, 0), url, font=fu)
w = bb[2] - bb[0]
pad = 36
x0 = (W - w) / 2 - pad
d.rounded_rectangle([x0, 520, x0 + w + 2 * pad, 600], radius=40, fill=(255, 255, 255))
d.text(((W - w) / 2, 532), url, font=fu, fill=(12, 60, 130))

img.save(out)
print("saved", out)
