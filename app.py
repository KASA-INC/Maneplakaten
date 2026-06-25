"""
Maneplakat - Shopify -> Gelato webhook-tjeneste
===============================================
Flyt:
  Shopify `orders/paid` webhook
    -> verifiser HMAC
    -> for hver maneplakat-linje: les Dato / Sted / Format fra line item properties
    -> render trykk-PNG (render_poster.render_bytes)
    -> last opp til S3-kompatibel lagring (offentlig URL)
    -> opprett EN Gelato-ordre (v4) med fil-URL og kundens adresse

Kjor: uvicorn app:app  (egnet for Render/Railway/Fly/VPS - alltid pa, tunge Python-deps)
Alle hemmeligheter settes som miljovariabler (se README).

VIKTIG: Skru AV Gelatos innebygde Shopify-kobling for disse plakat-produktene,
ellers blir ordrene opprettet to ganger (en gang av koblingen, en gang her).
"""
import base64, hashlib, hmac, json, logging, os

import boto3
import requests
from fastapi import FastAPI, Request, Response, BackgroundTasks

import render_poster

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("moonposter")

# --- Konfig (miljovariabler) ---
SHOPIFY_SECRET = os.environ.get("SHOPIFY_WEBHOOK_SECRET", "")
GELATO_API_KEY = os.environ.get("GELATO_API_KEY", "")
GELATO_URL     = "https://order.gelatoapis.com/v4/orders"
SHIPMENT       = os.environ.get("GELATO_SHIPMENT_METHOD", "normal")   # normal | standard | express
DPI            = int(os.environ.get("RENDER_DPI", "300"))
DRY_RUN        = os.environ.get("DRY_RUN", "0") == "1"               # bygg payload, ikke send

# S3-kompatibel lagring (AWS S3 / Cloudflare R2 / Supabase / Backblaze)
S3_BUCKET   = os.environ.get("S3_BUCKET", "")
S3_REGION   = os.environ.get("S3_REGION", "auto")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT") or None                 # f.eks. R2/Supabase-endpoint
PUBLIC_BASE = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")      # offentlig URL-prefiks til bucket

# Shopify-variant/format -> Gelato produkt-UID
PRODUCT_UIDS = {
    "A4":     "flat_a4-8x12-inch_170-gsm-65lb-uncoated_4-0_ver",
    "30x40":  "flat_300x400-mm-12x16-inch_170-gsm-65lb-uncoated_4-0_ver",
    "50x70":  "flat_500x700-mm-20x28-inch_170-gsm-65lb-uncoated_4-0_ver",
    "70x100": "flat_700x1000-mm-28x40-inch_170-gsm-65lb-uncoated_4-0_ver",
}

app = FastAPI()


def verify_hmac(raw: bytes, header: str) -> bool:
    if not SHOPIFY_SECRET or not header:
        return False
    digest = hmac.new(SHOPIFY_SECRET.encode(), raw, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), header)


def props_to_dict(line_item) -> dict:
    return {p.get("name", "").strip().lower(): (p.get("value") or "").strip()
            for p in (line_item.get("properties") or [])}


def normalize_format(s: str):
    if not s:
        return None
    k = s.lower().replace("×", "x").replace("cm", "").replace(" ", "").strip()
    if k in ("a4",): return "A4"
    for fmt in ("30x40", "50x70", "70x100"):
        if fmt in k:
            return fmt
    return None


def southern(place: str) -> bool:
    """Speilvend bare om sted er pa sorlige halvkule. Datafri default: nordlig (flip=1)."""
    south = ("australia", "new zealand", "sør-afrika", "sor-afrika", "argentina",
             "brasil", "chile", "peru", "uruguay", "namibia", "bolivia")
    return any(s in place.lower() for s in south)


def upload_png(data: bytes, key: str) -> str:
    s3 = boto3.client("s3", region_name=S3_REGION, endpoint_url=S3_ENDPOINT)
    extra = {"ContentType": "image/png"}
    if not S3_ENDPOINT:                      # AWS S3 stotter ACL; R2/Supabase bruker offentlig bucket
        extra["ACL"] = "public-read"
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=data, **extra)
    return f"{PUBLIC_BASE}/{key}"


def build_gelato_items(order) -> list:
    items = []
    for li in order.get("line_items", []):
        pr = props_to_dict(li)
        date = pr.get("dato") or pr.get("date")
        place = pr.get("sted") or pr.get("place") or ""
        text = pr.get("tekst") or pr.get("text") or ""
        fmt = normalize_format(pr.get("format") or li.get("variant_title") or li.get("title"))
        if not (date and fmt and fmt in PRODUCT_UIDS):
            continue                          # ikke en maneplakat-linje -> hopp over
        lat_raw = pr.get("_lat") or pr.get("lat")
        try:
            lat = float(lat_raw) if lat_raw not in (None, "") else None
        except ValueError:
            lat = None
        flip = -1 if southern(place) else 1   # reserve hvis breddegrad mangler i ordren
        png, info = render_poster.render_bytes(date, place, fmt, DPI, flip, text, lat)
        key = f"moonposters/{order['id']}/{li['id']}.png"
        url = upload_png(png, key)
        log.info("Rendret %s %s %s (%s%%, dreid %s\u00b0) -> %s",
                 fmt, date, place, info["pct"], info["rot"], url)
        items.append({
            "itemReferenceId": str(li["id"]),
            "productUid": PRODUCT_UIDS[fmt],
            "files": [{"type": "default", "url": url}],
            "quantity": int(li.get("quantity", 1)),
        })
    return items


def gelato_address(order) -> dict:
    a = order.get("shipping_address") or order.get("billing_address") or {}
    return {
        "firstName":   a.get("first_name", ""),
        "lastName":    a.get("last_name", ""),
        "companyName": a.get("company") or "",
        "addressLine1": a.get("address1", ""),
        "addressLine2": a.get("address2") or "",
        "city":        a.get("city", ""),
        "state":       a.get("province_code") or "",
        "postCode":    a.get("zip", ""),
        "country":     a.get("country_code", ""),     # ISO-2, som Gelato vil ha
        "email":       order.get("email", ""),
        "phone":       a.get("phone") or order.get("phone") or "",
    }


def process_order(order: dict):
    items = build_gelato_items(order)
    if not items:
        log.info("Ordre %s: ingen maneplakater, hopper over.", order.get("id"))
        return
    payload = {
        "orderType": "order",
        "orderReferenceId": f"shopify-{order['id']}",     # idempotens-noler pa Shopify-ordre-ID
        "customerReferenceId": str(order.get("customer", {}).get("id") or order.get("email", "")),
        "currency": order.get("currency", "NOK"),
        "items": items,
        "shipmentMethodUid": SHIPMENT,
        "shippingAddress": gelato_address(order),
    }
    if DRY_RUN:
        log.info("DRY_RUN - ville sendt til Gelato:\n%s", json.dumps(payload, indent=2, ensure_ascii=False))
        return payload
    r = requests.post(GELATO_URL, headers={"Content-Type": "application/json",
                                           "X-API-KEY": GELATO_API_KEY},
                      data=json.dumps(payload), timeout=60)
    if r.status_code >= 300:
        log.error("Gelato-feil %s: %s", r.status_code, r.text)
    else:
        log.info("Gelato-ordre opprettet: %s", r.json().get("id"))
    return payload


@app.post("/webhooks/orders-paid")
async def orders_paid(request: Request, bg: BackgroundTasks):
    raw = await request.body()
    if not verify_hmac(raw, request.headers.get("X-Shopify-Hmac-Sha256", "")):
        return Response(status_code=401, content="invalid hmac")
    order = json.loads(raw)
    bg.add_task(process_order, order)          # svar raskt; tungt arbeid i bakgrunnen
    return {"ok": True}


@app.get("/health")
def health():
    return {"status": "ok", "formats": list(PRODUCT_UIDS)}
