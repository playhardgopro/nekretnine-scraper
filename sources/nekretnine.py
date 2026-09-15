"""nekretnine.rs — весь список лежит в __NEXT_DATA__, отдельный запрос деталей не нужен.

Сайт работает на платформе Immobiliare, поэтому внутри попадаются итальянские
названия полей и значений. robots.txt запрещает внутренний API /search-list,
поэтому берём обычную страницу поиска, которая разрешена.
"""

import json
import re

from . import http

NAME = "nekretnine"
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def _surface(text):
    """'73 m²' -> 73, '1.003 m²' -> 1003. Точка здесь — разделитель тысяч."""
    m = re.match(r"[\d.,\s]+", str(text or ""))
    digits = re.sub(r"\D", "", m.group(0)) if m else ""
    return float(digits) if digits else None


def _rooms(text):
    """'3' -> 3.0, '1.5' -> 1.5, '5+' -> 5.0. А здесь точка — десятичная."""
    m = re.match(r"\d+(?:\.\d+)?", str(text or ""))
    return float(m.group(0)) if m else None


def fetch(url, page):
    u = http.with_params(url, "criterio=data&ordine=desc", *([f"pag={page}"] if page > 1 else []))
    m = NEXT_DATA.search(http.get(u).text)
    if not m:
        return []
    queries = json.loads(m.group(1))["props"]["pageProps"]["dehydratedState"]["queries"]
    results = queries[0]["state"]["data"]["results"]

    out = []
    for r in results:
        estate = r["realEstate"]
        prop = (estate.get("properties") or [{}])[0]
        loc = prop.get("location") or {}
        agency = (estate.get("advertiser") or {}).get("agency") or {}

        photos = (prop.get("multimedia") or {}).get("photos") or []
        image = photos[0].get("urls", {}).get("small") if photos else None
        if image:  # xxs-c — это превью 8 КБ, m-c уже нормальная картинка
            image = image.replace("/xxs-c.", "/m-c.")

        floor = prop.get("floor") or {}
        extra = [f"{floor['abbreviation']} эт."] if floor.get("abbreviation") else []
        if "lift" in (floor.get("value") or "").lower():
            extra.append("лифт")
        out.append({
            "id": f"{NAME}:{estate['id']}",
            "url": r["seo"]["url"],
            "price": (estate.get("price") or {}).get("value"),
            "m2": _surface(prop.get("surface")),
            "rooms": _rooms(prop.get("rooms")),
            "title": estate.get("title") or prop.get("caption") or "Квартира",
            "place": ", ".join(x for x in (loc.get("city"), loc.get("macrozone")) if x),
            "description": prop.get("description") or "",
            "image": image,
            "agency": agency.get("displayName") or None,
            "is_agency": bool(agency),
            "furnished": None,        # сайт не отдаёт это отдельным полем
            "extra": extra,
            "posted": None,           # даты публикации в выдаче нет
            "location": {"latitude": loc.get("latitude"), "longitude": loc.get("longitude")},
        })
    return out
