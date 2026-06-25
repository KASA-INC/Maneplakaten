"""
Maneplakat - trykk-renderer (v3: gradvis breddegrad-rotasjon).
Myke lag (glod/skygge) rendres pa lav opplosning og skaleres opp; tekst pa full
opplosning -> rask 300 dpi. Output: sRGB PNG i (trim + 4mm bleed), passer Gelato.
Farger fra utkast: navy #161525, krem #FFEEDE.

Manens orientering folger breddegraden (alternativ A, lineaer):
    dreining = 90 grader - breddegrad
        Nordpolen (+90)  ->   0 grader  (rettvendt, lys til hoyre for voksende mane)
        Oslo     (+59.9) ->  ~30 grader
        Ekvator    (0)   ->  90 grader  (terminator vannrett - "smilende mane")
        Sydney   (-33.9) -> ~124 grader
        Sydpolen (-90)   -> 180 grader  (opp-ned)
Rotasjonen er en EKTE rotasjon av hele skiva (fase + tekstur), ikke en speiling.
"""
import math, os, sys
import numpy as np
import ephem
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

FONT_FILE = "Afacad-VariableFont_wght.ttf"
# Hoyopplost manetekstur (kremtonet naerside-skive). Lag den med prep_moon.py.
# For produksjon: bruk NASA SVS CGI Moon Kit (public domain) som kilde.
try:
    MOON_TEX = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "moon-texture.png")).convert("RGBA")
except Exception:
    MOON_TEX = None
NAVY = (22, 21, 37); CREAM = (255, 238, 222); LITNAVY = (50, 48, 78)
FORMATS = {"A4": (21.0, 29.7), "30x40": (30.0, 40.0), "50x70": (50.0, 70.0), "70x100": (70.0, 100.0)}
# Fontskala: tekst vokser sub-lineaert med plakatbredden, ikke 1:1.
#   FONT_EXP = 0 -> lik font pa alle format ; 1 -> gammel lineaer ; 0.5 -> mild vekst (kvadratrot)
# Referanseformatet (FONT_REF_W) beholder den gamle storrelsen; mindre format blir
# relativt litt storre, storre format relativt litt mindre.
# Fontskala: dato-storrelsen folger en potenskurve i plakatbredden, forankret i
# referanseformatet (som beholder sin storrelse). Mindre format skaleres NED.
#   FONT_EXP = 0 -> lik font pa alle format ; 1 -> lineaer ; hoyere = mer nedskalering av sma format.
FONT_REF_W  = 50.0    # referanseformat (cm bredde) - 50x70 holdes uendret
FONT_REF_FD = 2.3238  # dato-storrelse (cm) ved referanseformatet (= dagens 50x70-verdi)
FONT_EXP    = 0.60
# Tekstblokk: linjene stables med LIK LUFT mellom versalboksene (ikke mellom
# grunnlinjene), slik at datoen blir visuelt midtstilt og avstandene like.
# Hele blokken sentreres pa midtpunktet mellom bunnen av manen og bunnen av plakaten.
CAP_RATIO  = 0.65   # Afacads versalhoyde som andel av fontstorrelsen (malt)
LINE_GAP   = 0.46   # luft mellom versalboksene, som andel av dato-storrelsen (Fd)
FT_LINE_GAP = 0.23  # linjeavstand for fritekst (halvparten av LINE_GAP - tettere avsnitt)
FT_SECTION_GAP = 0.85  # separasjon mellom hovedblokk og fritekst (x Fd)
# Fritekst-spaltens bredde = midt mellom manens ytterkant og datoens ytterkant,
# dvs. (manediameter + datobredde) / 2. Parameterfri - skalerer naturlig per format.
DAYS = ["søndag","mandag","tirsdag","onsdag","torsdag","fredag","lørdag"]


def rotation_deg(lat):
    """Alternativ A (lineaer): dreining i grader, med klokka, ut fra breddegrad."""
    lat = max(-90.0, min(90.0, float(lat)))
    return 90.0 - lat


def format_place(s):
    # Stor forbokstav paa stedsnavn; ord som allerede har versaler (USA) bevares.
    return " ".join(w if any(c.isupper() for c in w) else w[:1].upper()+w[1:]
                    for w in s.split())


def cycle_pos(date):
    d = ephem.Date(date); pn, nn = ephem.previous_new_moon(d), ephem.next_new_moon(d)
    return (d - pn) / (nn - pn)


def lit_points(cx, cy, r, p, n=400):
    """Terminator-omrisset for fasen, i nordlig rettvendt orientering."""
    rx = abs(math.cos(2*math.pi*p))*r
    sl = 1 if p < 0.5 else -1
    st = 1 if (math.floor(p*4) % 2 == 0) else -1
    out = []
    for i in range(n+1):
        t = -math.pi/2 + math.pi*i/n; out.append((cx+sl*r*math.cos(t), cy+r*math.sin(t)))
    for i in range(n+1):
        t = math.pi/2 - math.pi*i/n; out.append((cx+st*rx*math.cos(t), cy+r*math.sin(t)))
    return out


def moon_layer(W, H, cx, cy, r, p):
    """Den tonale manen (bakgrunn + volum + glod + sigd) i nordlig rettvendt
    orientering. Rotasjon etter breddegrad gjores av kalleren."""
    img = Image.new("RGB", (W, H), NAVY)
    disc = Image.new("L", (W, H), 0); ImageDraw.Draw(disc).ellipse([cx-r, cy-r, cx+r, cy+r], fill=255)
    # volum pa mork side: lyskilde mot belyst kant - bredere/mykere for tydeligere indre glod
    lx = cx + (-0.32*r if p < 0.5 else 0.32*r); ly = cy - 0.28*r
    yy, xx = np.mgrid[0:H, 0:W]
    val = np.clip(1 - np.sqrt((xx-lx)**2 + (yy-ly)**2)/(2.05*r), 0, 1)**1.32
    grad = Image.fromarray((val*255).astype("uint8"), "L")
    img.paste(Image.new("RGB", (W, H), LITNAVY), (0, 0), Image.composite(grad, Image.new("L", (W, H), 0), disc))
    # belyst sigd + glod
    lit = Image.new("L", (W, H), 0); ImageDraw.Draw(lit).polygon(lit_points(cx, cy, r, p), fill=255)
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
        tex = MOON_TEX.resize((2*R, 2*R), Image.LANCZOS)   # alltid rettvendt - rotasjon skjer senere
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


def balance_lines(words, width_of, max_w):
    """InDesign-aktig linjedeling UTEN krymping: faerrest mulig linjer, mest mulig
    like brede, og helst ikke ett ord alene pa en linje. width_of(streng)->bredde."""
    import itertools
    n = len(words)
    if n <= 1:
        return [" ".join(words)]
    def greedy(mw):                                  # gradig fyll -> antall linjer som trengs
        out, cur = [], []
        for w in words:
            if cur and width_of(" ".join(cur+[w])) > mw:
                out.append(cur); cur = [w]
            else:
                cur.append(w)
        if cur: out.append(cur)
        return out
    Lmin = len(greedy(max_w))
    if Lmin <= 1:
        return [" ".join(words)]
    best = None
    avoidable = n >= 2*Lmin                          # enslige ord kan bare unngas med nok ord
    for cuts in itertools.combinations(range(1, n), Lmin-1):
        b = (0,) + cuts + (n,)
        parts = [words[b[i]:b[i+1]] for i in range(Lmin)]
        widths = [width_of(" ".join(p)) for p in parts]
        if max(widths) > max_w:
            continue
        lone = sum(1 for p in parts if len(p) == 1)
        cost = ((lone if avoidable else 0), round(max(widths)), round(max(widths)-min(widths)))
        if best is None or cost < best[0]:
            best = (cost, [" ".join(p) for p in parts])
    if best is None:                                 # langt enkeltord e.l. -> gradig, tillat overflyt
        return [" ".join(p) for p in greedy(max_w)]
    return best[1]


def build_image(date_str, place, fmt, dpi=300, flip=1, freetext="", lat=None):
    """Bygger plakaten og returnerer (PIL.Image, infodict).

    lat  : breddegrad (-90..90). Gir gradvis rotasjon (alternativ A).
    flip : bakoverkompatibel reserve nar lat mangler (flip<0 => 180 grader / sor).
    """
    if fmt not in FORMATS:
        raise ValueError(f"Ukjent format: {fmt}. Gyldige: {list(FORMATS)}")
    Wc, Hc = FORMATS[fmt]
    def px(cm): return round(cm/2.54*dpi)
    bl, tw, th = px(0.4), px(Wc), px(Hc)
    Wp, Hp = tw+2*bl, th+2*bl
    cx, cy, r = bl+tw/2, bl+0.5*tw, 0.4*tw
    C = bl + (0.9*tw + th)/2
    Fd = FONT_REF_FD*(Wc/FONT_REF_W)**FONT_EXP/2.54*dpi    # sub-lineaer, forankret i 50x70
    Fs = Fd/2

    # dreining: bruk breddegrad om oppgitt, ellers den gamle nord/sor-reserven
    if lat is not None:
        rot = rotation_deg(lat)
    else:
        rot = 180.0 if flip < 0 else 0.0

    y, m, d = (int(v) for v in date_str.split("-"))
    dt = ephem.Date((y, m, d, 12, 0, 0)); p = cycle_pos(dt)
    weekday = DAYS[(dt.datetime().weekday()+1) % 7].upper(); datestr = f"{d:02d}.{m:02d}.{y}"

    s = min(1.0, 2200/max(Wp, Hp))                      # myke lag pa lav opplosning
    moon = moon_layer(round(Wp*s), round(Hp*s), cx*s, cy*s, r*s, p)
    if rot % 360 != 0:
        # PIL roterer mot klokka for positive grader -> negativ vinkel = med klokka.
        moon = moon.rotate(-rot, resample=Image.BICUBIC, center=(cx*s, cy*s), fillcolor=NAVY)
    img = moon.resize((Wp, Hp), Image.LANCZOS)

    draw = ImageDraw.Draw(img)                            # tekst pa full opplosning (roteres aldri)
    ch_s, ch_d, G = CAP_RATIO*Fs, CAP_RATIO*Fd, LINE_GAP*Fd

    main = [(weekday, Fs, Fs*0.30, ch_s, "l"),
            (datestr, Fd, 0.0,     ch_d, "m"),
            (format_place(place), Fs, Fs*0.12, ch_s, "l")]
    main_total = sum(ch for *_, ch, _ in main) + G*(len(main)-1)

    # Fritekst: ingen krymping - bryt i balanserte linjer (ikke ett ord alene).
    ft = (freetext or "").strip()
    ftlines = []
    if ft:
        ftr = Fs*0.06; fnt = load_font(Fs)
        def w_of(s, fnt=fnt, ftr=ftr):
            return sum(draw.textlength(c, font=fnt) for c in s) + ftr*max(0, len(s)-1)
        date_w = draw.textlength(datestr, font=load_font(Fd))   # datolinjens bredde
        ft_col = r + date_w/2                                    # midt mellom manens og datoens ytterkant
        ftlines = balance_lines(ft.split(), w_of, ft_col)
    Gf = FT_LINE_GAP*Fd
    sect = FT_SECTION_GAP*Fd
    ft_h = (len(ftlines)*ch_s + (len(ftlines)-1)*Gf) if ftlines else 0
    comp = main_total + ((sect + ft_h) if ftlines else 0)

    # Hele komposisjonen (hovedblokk + fritekst) sentreres pa C -> jevn marg topp/bunn.
    yb = C - comp/2
    for i, (text, fsz, tr, ch, mode) in enumerate(main):
        baseline = yb + ch
        if mode == "m":
            draw.text((cx, baseline), text, font=load_font(fsz), fill=CREAM, anchor="ms")
        else:
            tracked(draw, text, load_font(fsz), cx, baseline, tr, CREAM)
        yb += ch + (G if i < len(main)-1 else 0)
    if ftlines:
        yb += sect
        for j, line in enumerate(ftlines):
            tracked(draw, line, fnt, cx, yb + ch_s, ftr, CREAM)
            yb += ch_s + (Gf if j < len(ftlines)-1 else 0)

    info = {"weekday": weekday, "date": datestr, "phase": round(p, 3),
            "pct": round((1-math.cos(2*math.pi*p))/2*100), "rot": round(rot, 1), "px": (Wp, Hp)}
    return img, info


def render(date_str, place, fmt, out, dpi=300, flip=1, freetext="", lat=None):
    img, info = build_image(date_str, place, fmt, dpi, flip, freetext, lat)
    img.save(out, "PNG", dpi=(dpi, dpi))
    print(f"{fmt} @{dpi}dpi {info['px'][0]}x{info['px'][1]}px: "
          f"{info['weekday']} {info['date']} | {info['pct']}% | dreid {info['rot']}\u00b0 -> {out}")
    return info


def render_bytes(date_str, place, fmt, dpi=300, flip=1, freetext="", lat=None):
    """Returnerer (png_bytes, infodict) - til bruk i webhook uten diskskriving."""
    import io
    img, info = build_image(date_str, place, fmt, dpi, flip, freetext, lat)
    buf = io.BytesIO()
    img.save(buf, "PNG", dpi=(dpi, dpi))
    return buf.getvalue(), info


if __name__ == "__main__":
    a = sys.argv
    lat = float(a[7]) if len(a) > 7 else None
    render(a[1] if len(a)>1 else "1984-04-09", a[2] if len(a)>2 else "Oslo – Norge",
           a[3] if len(a)>3 else "50x70", a[4] if len(a)>4 else "maneplakat.png",
           int(a[5]) if len(a)>5 else 300, 1, a[6] if len(a)>6 else "", lat)
