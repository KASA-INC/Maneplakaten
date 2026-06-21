"""Projiser et ekvirektangulart manekart til en kremtonet naerside-skive (RGBA PNG).
Bruk samme skript pa NASAs hoyopploste kart for produksjon:
    python3 prep_moon.py <equirect-kart> moon-texture.png 2048
"""
import sys
import numpy as np
from PIL import Image

src = sys.argv[1] if len(sys.argv) > 1 else "moon_src.jpg"
out = sys.argv[2] if len(sys.argv) > 2 else "moon-texture.png"
D   = int(sys.argv[3]) if len(sys.argv) > 3 else 2048
R   = D / 2.0
C_LOW  = np.array([150, 135, 120])   # warme, morkere parti (hav/krater)
C_HIGH = np.array([255, 238, 222])   # krem (hoylandet) - matcher designet

m = np.asarray(Image.open(src).convert("L"), float)
Hm, Wm = m.shape
yy, xx = np.mgrid[0:D, 0:D]
nx = (xx - R) / R
ny = (yy - R) / R
rr = nx*nx + ny*ny
nz = np.sqrt(np.clip(1 - rr, 0, 1))
lat = np.arcsin(np.clip(-ny, -1, 1))          # naerside, sentrert lon 0
lon = np.arctan2(nx, nz)
u = np.clip(((lon/(2*np.pi)) + 0.5) * (Wm-1), 0, Wm-1).astype(int)
v = np.clip((0.5 - lat/np.pi) * (Hm-1), 0, Hm-1).astype(int)
L = m[v, u] / 255.0

t = np.clip((L - 0.12) / 0.72, 0, 1) ** 0.9   # litt kontraststrekk
t *= (0.60 + 0.40 * nz**0.5)                  # mild kantmorkning (limb darkening)
t = np.clip(t, 0, 1)[..., None]
rgb = (C_LOW + (C_HIGH - C_LOW) * t).astype(np.uint8)

dist = np.sqrt(rr)
alpha = np.clip((1.0 - dist) / (2.0/R), 0, 1)  # mykt antialiasert kant (~2px)
alpha = (alpha * 255).astype(np.uint8)

out_img = np.dstack([rgb, alpha])
Image.fromarray(out_img, "RGBA").save(out)
print("Lagret", out, (D, D))
