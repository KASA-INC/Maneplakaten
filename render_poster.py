"""
Maneplakat - trykk-renderer (v2: tonal sRGB-render, Afacad til preview + trykk)
Myke lag (glod/skygge) rendres pa lav opplosning og skaleres opp; tekst pa full
opplosning -> rask 300 dpi. Output: sRGB PNG i (trim + 4mm bleed), passer Gelato.
Farger fra utkast: navy #161525, krem #FFEEDE.
"""
import math, os, sys
import numpy as np
import ephem
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

FONT_FILE = "/mnt/user-data/uploads/Afacad-VariableFont_wght.ttf"
# Hoyopplost manetekstur (kremtonet naerside-skive). Lag den med prep_moon.py.
# For produksjon: bruk NASA SVS CGI Moon Kit (public domain) som kilde.
try:
    MOON_TEX = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "moon-texture.png")).convert("RGBA")
except Exception:
    MOON_TEX = None
NAVY = (22, 21, 37); CREAM = (255, 238, 222); LITNAVY = (50, 48, 78)
FORMATS = {"A4": (21.0, 29.7), "30x40": (30.0, 40.0), "50x70": (50.0, 70.0), "70x100": (70.0, 100.0)}
DAYS = ["søndag","mandag","tirsdag","onsdag","torsdag","fredag","lørdag"]


def format_place(s):
    # Stor forbokstav paa stedsnavn; ord som allerede har versaler (USA) bevares.
    return " ".join(w if any(c.isupper() for c in w) else w[:1].upper()+w[1:]
                    for w in s.split())


def cycle_pos(date):
    d = ephem.Date(date); pn, nn = ephem.previous_new_moon(d), ephem.next_new_moon(d)
    return (d - pn) / (nn - pn)


def lit_points(cx, cy, r, p, n=400, flip=1):
    rx = abs(math.cos(2*math.pi*p))*r
    sl = (1 if p < 0.5 else -1) * flip
    st = (1 if (math.floor(p*4) % 2 == 0) else -1) * flip
    out = []
    for i in range(n+1):
        t = -math.pi/2 + math.pi*i/n; out.append((cx+sl*r*math.cos(t), cy+r*math.sin(t)))
    for i in range(n+1):
        t = math.pi/2 - math.pi*i/n; out.append((cx+st*rx*math.cos(t), cy+r*math.sin(t)))
    return out


def moon_layer(W, H, cx, cy, r, p, flip=1):
    """Den tonale manen (bakgrunn + volum + glod + sigd) - rendres her pa arbeidsopplosning."""
    img = Image.new("RGB", (W, H), NAVY)
    disc = Image.new("L", (W, H), 0); ImageDraw.Draw(disc).ellipse([cx-r, cy-r, cx+r, cy+r], fill=255)
    # volum pa mork side: lyskilde mot belyst kant - bredere/mykere for tydeligere indre glod
    lx = cx + flip*(-0.32*r if p < 0.5 else 0.32*r); ly = cy - 0.28*r
    yy, xx = np.mgrid[0:H, 0:W]
    val = np.clip(1 - np.sqrt((xx-lx)**2 + (yy-ly)**2)/(2.05*r), 0, 1)**1.32
    grad = Image.fromarray((val*255).astype("uint8"), "L")
    img.paste(Image.new("RGB", (W, H), LITNAVY), (0, 0), Image.composite(grad, Image.new("L", (W, H), 0), disc))
    # belyst sigd + glod
    lit = Image.new("L", (W, H), 0); ImageDraw.Draw(lit).polygon(lit_points(cx, cy, r, p, flip=flip), fill=255)
    for rad, k in [(r*0.16, 0.55), (r*0.06, 0.85)]:
        g = lit.filter(ImageFilter.GaussianBlur(rad)).point(lambda v, k=k: int(v*k))
        img.paste(Image.new("RGB", (W, H), CREAM), (0, 0), g)
    ring = Image.new("L", (W, H), 0)
    ImageDraw.Draw(ring).ellipse([cx-r, cy-r, cx+r, cy+r], outline=255, width=max(2, int(r*0.014)))
    ring = ring.filter(ImageFilter.GaussianBlur(r*0.06)).point(lambda v: int(v*0.42))
    img.paste(Image.new("RGB", (W, H), CREAM), (0, 0), ring)
    # belyst del: ekte manetekstur maskert til fasen (mykt mot terminator)
    litsoft = lit.filter(ImageFilter.GaussianBlur(max(1, r*0.006)))
    if MOON_TEX is not None:
        R = max(1, int(round(r)))
        tex = MOON_TEX.resize((2*R, 2*R), Image.LANCZOS)
        if flip < 0:
            tex = tex.transpose(Image.FLIP_LEFT_RIGHT)
        moonf = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        moonf.paste(tex, (int(round(cx))-R, int(round(cy))-R), tex)
        mask = ImageChops.multiply(litsoft, moonf.split()[3])
        img.paste(moonf.convert("RGB"), (0, 0), mask)
    else:
        img.paste(Image.new("RGB", (W, H), CREAM), (0, 0), litsoft)
    return img


def load_font(size, wght=400):
    f = ImageFont.truetype(FONT_FILE, max(1, int(size)))
    try: f.set_variation_by_axes([wght])
    except Exception: pass
    return f


def tracked(draw, text, font, cx, baseline, tr, fill):
    ws = [draw.textlength(ch, font=font) for ch in text]
    x = cx - (sum(ws) + tr*max(0, len(text)-1))/2
    for ch, w in zip(text, ws):
        draw.text((x, baseline), ch, font=font, fill=fill, anchor="ls"); x += w + tr


def build_image(date_str, place, fmt, dpi=300, flip=1, freetext=""):
    """Bygger plakaten og returnerer (PIL.Image, infodict). flip=-1 speilvender (sorlig halvkule)."""
    if fmt not in FORMATS:
        raise ValueError(f"Ukjent format: {fmt}. Gyldige: {list(FORMATS)}")
    Wc, Hc = FORMATS[fmt]
    def px(cm): return round(cm/2.54*dpi)
    bl, tw, th = px(0.4), px(Wc), px(Hc)
    Wp, Hp = tw+2*bl, th+2*bl
    cx, cy, r = bl+tw/2, bl+0.5*tw, 0.4*tw
    C = bl + (0.9*tw + th)/2
    Fd = 0.06*tw; Fs = Fd/2; gap = 0.95*Fd

    y, m, d = (int(v) for v in date_str.split("-"))
    dt = ephem.Date((y, m, d, 12, 0, 0)); p = cycle_pos(dt)
    weekday = DAYS[(dt.datetime().weekday()+1) % 7].upper(); datestr = f"{d:02d}.{m:02d}.{y}"

    s = min(1.0, 2200/max(Wp, Hp))                      # myke lag pa lav opplosning
    img = moon_layer(round(Wp*s), round(Hp*s), cx*s, cy*s, r*s, p, flip).resize((Wp, Hp), Image.LANCZOS)

    draw = ImageDraw.Draw(img)                            # tekst pa full opplosning
    ft = (freetext or "").strip()
    base = C + 0.40*Fd
    big = 2.0*gap
    if ft:
        base -= big/2.0                                  # loft blokken litt nar fritekst brukes
    tracked(draw, weekday, load_font(Fs), cx, base-gap, Fs*0.30, CREAM)
    draw.text((cx, base), datestr, font=load_font(Fd), fill=CREAM, anchor="ms")
    tracked(draw, format_place(place), load_font(Fs), cx, base+gap, Fs*0.12, CREAM)
    if ft:
        Ff, tr = Fs, Fs*0.06                             # krymp om fritekst er bred
        while Ff > Fs*0.5 and sum(draw.textlength(ch, font=load_font(Ff)) for ch in ft) + tr*max(0, len(ft)-1) > 0.82*tw:
            Ff *= 0.94; tr = Ff*0.06
        tracked(draw, ft, load_font(Ff, 400), cx, base+gap+big, tr, CREAM)

    info = {"weekday": weekday, "date": datestr, "phase": round(p, 3),
            "pct": round((1-math.cos(2*math.pi*p))/2*100), "px": (Wp, Hp)}
    return img, info


def render(date_str, place, fmt, out, dpi=300, flip=1, freetext=""):
    img, info = build_image(date_str, place, fmt, dpi, flip, freetext)
    img.save(out, "PNG", dpi=(dpi, dpi))
    print(f"{fmt} @{dpi}dpi {info['px'][0]}x{info['px'][1]}px: "
          f"{info['weekday']} {info['date']} | {info['pct']}% -> {out}")
    return info


def render_bytes(date_str, place, fmt, dpi=300, flip=1, freetext=""):
    """Returnerer (png_bytes, infodict) - til bruk i webhook uten diskskriving."""
    import io
    img, info = build_image(date_str, place, fmt, dpi, flip, freetext)
    buf = io.BytesIO()
    img.save(buf, "PNG", dpi=(dpi, dpi))
    return buf.getvalue(), info


if __name__ == "__main__":
    a = sys.argv
    render(a[1] if len(a)>1 else "1984-04-09", a[2] if len(a)>2 else "Oslo – Norge",
           a[3] if len(a)>3 else "50x70", a[4] if len(a)>4 else "maneplakat.png",
           int(a[5]) if len(a)>5 else 300, 1, a[6] if len(a)>6 else "")
