"""4zida.rs — список из ld+json на странице поиска, детали из открытого JSON API."""

import datetime as dt
import json
import re

from . import http

NAME = "4zida"
LD_JSON = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
AD_API = "https://api.4zida.rs/v6/ads/"


def fetch(url, page):
    """Дешёвый список: id, ссылка, цена, площадь, комнаты — без запроса деталей."""
    u = http.with_params(url, "sortiranje=najnoviji", *([f"strana={page}"] if page > 1 else []))
    for block in LD_JSON.findall(http.get(u).text):
        data = json.loads(block)
        if data.get("@type") != "ItemList":
            continue
        out = []
        for entry in data.get("itemListElement", []):
            item = entry.get("item", {})
            offered = item.get("itemOffered", {})
            out.append({
                "id": f"{NAME}:{entry['url'].rsplit('/', 1)[1]}",
                "url": entry["url"],
                "price": item.get("offers", {}).get("price"),
                "m2": offered.get("floorSize", {}).get("value"),
                "rooms": offered.get("numberOfRooms"),
            })
        return out
    return []


def enrich(item):
    """Полная карточка. Возвращает None, если объявление уже неактивно."""
    ad = http.get(AD_API + item["id"].split(":", 1)[1]).json()
    if ad.get("status") != "active":
        return None

    extra = []
    if ad.get("redactedFloor") is not None:
        extra.append(f"{ad['redactedFloor']}/{ad.get('redactedTotalFloors', '?')} эт.")
    for flag, label in (("elevator", "лифт"), ("terrace", "терраса"), ("garage", "гараж")):
        if ad.get(flag):
            extra.append(label)

    agency = (ad.get("author") or {}).get("agency") or {}
    images = ad.get("images") or []

    return {**item,
            "title": ad.get("structureName") or "Квартира",
            "place": ", ".join(p["title"] for p in (ad.get("placeMetaData") or [])[:2]),
            "description": ad.get("humanReadableDescription") or "",
            "images": [u for i in images
                       if (u := i.get("adDetails", {}).get("730x396_fill_0_jpeg"))],
            "agency": agency.get("title") or agency.get("name") or None,
            "is_agency": bool(agency),
            "furnished": ad.get("furnished"),
            "extra": extra,
            # Время создания зашито в первые 4 байта ObjectId.
            "posted": dt.datetime.fromtimestamp(
                int(item["id"].split(":", 1)[1][:8], 16), dt.timezone.utc),
            "location": ad.get("location") or {}}
