import random
from PIL import Image, ImageDraw, ImageFilter, ImageChops

S = 1600  # draw big, downscale for smooth edges
OUT = 800
random.seed(7)

def brain_mask():
    m = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(m)
    cx, cy = S * 0.5, S * 0.47
    # Side-view brain silhouette from overlapping lobes.
    lobes = [(-330, -60, 250), (-170, -210, 230), (40, -250, 240), (240, -170, 230),
             (330, 10, 220), (190, 150, 210), (-40, 130, 230), (-260, 120, 210)]
    for dx, dy, r in lobes:
        d.ellipse([cx + dx - r, cy + dy - r * 0.92, cx + dx + r, cy + dy + r * 0.92], fill=255)
    # Cerebellum and brainstem.
    d.ellipse([cx + 140, cy + 210, cx + 420, cy + 400], fill=255)
    d.polygon([(cx + 40, cy + 250), (cx + 170, cy + 250), (cx + 150, cy + 500), (cx + 75, cy + 500)], fill=255)
    return m

def smooth(points, steps=24):
    pts = [points[0]] + points + [points[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for t in range(steps):
            t /= steps
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
                                    + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3) for k in range(2)))
    out.append(points[-1])
    return out


def sulci(mask):
    """Dark folds drawn inside the brain."""
    lines = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(lines)
    cx, cy = S * 0.5, S * 0.47
    w = 30
    paths = [
        [(-470, -20), (-360, -120), (-240, -70), (-150, -170)],
        [(-330, 70), (-200, 10), (-80, 70), (40, 20)],
        [(-90, -330), (-60, -230), (-130, -140), (-60, -60)],
        [(130, -340), (90, -240), (170, -160), (120, -70)],
        [(330, -250), (270, -150), (350, -60)],
        [(150, 60), (270, 10), (400, 60)],
        [(-380, 200), (-260, 250), (-140, 200)],
        [(-30, 230), (80, 190), (180, 240)],
        [(190, 300), (300, 330), (390, 300)],
    ]
    for p in paths:
        pts = [(cx + x, cy + y) for x, y in smooth(p)]
        d.line(pts, fill=255, width=w)
        for x, y in (pts[0], pts[-1]):
            d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=255)
        for x, y in pts[::6]:
            d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=255)
    return ImageChops.multiply(lines, mask)

def colorize(mask, color):
    layer = Image.new("RGBA", (S, S), color + (0,))
    layer.putalpha(mask)
    return layer

def shift(img, dx, dy):
    out = Image.new(img.mode, img.size, (0, 0, 0, 0))
    out.paste(img, (dx, dy))
    return out

def slice_glitch(img, n=4):
    out = img.copy()
    for _ in range(n):
        y = random.randint(int(S * 0.2), int(S * 0.75))
        h = random.randint(22, 46)
        dx = random.choice([-1, 1]) * random.randint(40, 80)
        band = img.crop((0, y, S, y + h))
        out.paste((0, 0, 0, 0), (0, y, S, y + h))
        out.paste(band, (dx, y), band)
    return out

# Background: deep navy with a soft violet glow.
bg = Image.new("RGB", (S, S), (12, 12, 28))
glow = Image.new("L", (S, S), 0)
ImageDraw.Draw(glow).ellipse([S * 0.12, S * 0.1, S * 0.88, S * 0.86], fill=150)
glow = glow.filter(ImageFilter.GaussianBlur(170))
bg = Image.composite(Image.new("RGB", (S, S), (70, 30, 120)), bg, glow)

mask = brain_mask()
folds = sulci(mask)
brain = ImageChops.subtract(mask, folds)

cyan = colorize(brain, (0, 235, 255))
pink = colorize(brain, (255, 40, 170))
white = colorize(brain, (245, 245, 255))

canvas = bg.convert("RGBA")
canvas = Image.alpha_composite(canvas, shift(pink, -34, 6))
canvas = Image.alpha_composite(canvas, shift(cyan, 34, -6))
canvas = Image.alpha_composite(canvas, slice_glitch(white))

# Scanlines for a subtle screen feel.
scan = Image.new("RGBA", (S, S), (0, 0, 0, 0))
sd = ImageDraw.Draw(scan)
for y in range(0, S, 10):
    sd.line([(0, y), (S, y)], fill=(0, 0, 0, 38), width=3)
canvas = Image.alpha_composite(canvas, scan)

final = canvas.convert("RGB").resize((OUT, OUT), Image.LANCZOS)
final.save("/home/user/project1/assets/branding/brain_glitch_profile.png", optimize=True)

# Preview of how YouTube crops it (circle).
prev = final.copy()
circle = Image.new("L", (OUT, OUT), 0)
ImageDraw.Draw(circle).ellipse([0, 0, OUT, OUT], fill=255)
bgw = Image.new("RGB", (OUT, OUT), (255, 255, 255))
Image.composite(prev, bgw, circle).resize((300, 300)).save(
    "assets/branding/circle_preview.png")
print("ok")
