# Deploy – Måneplakaten (Render + Shopify)

Løsningen har to hjem:

- **Denne mappa (backend)** → en Python-tjener (Render). Tar imot ordrer, renderer, sender til Gelato.
- **Shopify (temaet)** → får bare `moon-personalizer.liquid` (snippet) + `moon-texture.png` (Files). Disse ligger IKKE i dette repoet.

---

## Del 1 – Backend på Render

### 1. Legg mappa i et GitHub-repo
Last opp hele denne mappa til et nytt (gjerne privat) GitHub-repo. Filene må ligge i rota:
```
app.py
render_poster.py
requirements.txt
moon-texture.png
Afacad-VariableFont_wght.ttf
render.yaml
.python-version
tools/prep_moon.py   (valgfritt – verktøy, kjøres bare lokalt)
```

### 2. Opprett tjenesten på Render
- Render → **New → Web Service** → koble til GitHub-repoet.
- Render leser `render.yaml` automatisk. Hvis du setter den opp manuelt i stedet:
  - Runtime: **Python**
  - Build command: `pip install -r requirements.txt`
  - Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
  - Instance type: **Standard** (70×100 på 300 dpi trenger romslig RAM).
  - Health check path: `/health`

### 3. Sett miljøvariabler (Environment)
| Variabel | Verdi |
|---|---|
| `SHOPIFY_WEBHOOK_SECRET` | Signeringsnøkkel fra Shopify (se Del 3) |
| `GELATO_API_KEY` | API-nøkkel fra Gelato (Dashboard → API) |
| `GELATO_SHIPMENT_METHOD` | `normal` (eller `express`) |
| `RENDER_DPI` | `300` |
| `S3_BUCKET` | Navn på en **offentlig** bøtte |
| `S3_REGION` | `auto` (R2) eller f.eks. `eu-north-1` (AWS) |
| `S3_ENDPOINT` | R2/Supabase-endpoint, tom for AWS S3 |
| `PUBLIC_BASE_URL` | Offentlig URL-prefiks til bøtta |
| `DRY_RUN` | Start på `1`, sett til `0` når alt funker |

### 4. Lagring for de ferdige filene
Gelato må kunne hente trykkfilen via en offentlig URL. Enkleste vei: **Cloudflare R2** (gratis nivå, S3-kompatibel) med en offentlig bøtte. Sett `S3_BUCKET`, `S3_ENDPOINT` (R2-endepunktet) og `PUBLIC_BASE_URL` (den offentlige adressen til bøtta). AWS S3 og Supabase Storage funker også.

Når tjenesten kjører, gir Render deg en URL som `https://maneplakat.onrender.com`. Test den: `…/health` skal svare `{"status":"ok"}`.

---

## Del 2 – Shopify-temaet
1. **Snippet:** Edit code → Snippets → Add a new snippet → navn `moon-personalizer` → lim inn innholdet fra `moon-personalizer.liquid`.
2. **Tekstur:** Content → Files → last opp `moon-texture.png` → kopier URL-en → lim inn i `MOON_URL` øverst i snippet-en.
3. **Blokk:** På produktet (Theme editor) → Add block → Custom Liquid, over kjøpsknappen, med innhold: `{% render 'moon-personalizer' %}`
4. **Varianter:** Gi størrelsene navnene `A4`, `30×40`, `50×70`, `70×100` (så serveren velger riktig Gelato-UID).

---

## Del 3 – Koble Shopify til backend
1. Shopify → Settings → **Notifications → Webhooks** → Create webhook.
2. Event: **Order payment** (`orders/paid`), format JSON, URL: `https://din-tjeneste.onrender.com/webhooks/orders-paid`.
3. Nederst på samme side står en **signeringsnøkkel** – kopier den til `SHOPIFY_WEBHOOK_SECRET` på Render.

---

## Del 4 – Viktig før lansering
- **Skru av Gelatos innebygde Shopify-kobling** for plakat-produktene, ellers opprettes ordrene to ganger.
- Test først med `DRY_RUN=1`: legg en testordre, og se i Render-loggen at payloaden bygges riktig. Sett så `DRY_RUN=0`.
- **Høyoppløst måne:** bytt demo-`moon-texture.png` mot en laget fra NASA SVS CGI Moon Kit:
  `python3 tools/prep_moon.py nasa-fargekart.tif moon-texture.png 4096`, og last den opp begge steder (repoet + Shopify Files).
- **RAM:** hvis 70×100 feiler med minnefeil, øk instanstype på Render.
