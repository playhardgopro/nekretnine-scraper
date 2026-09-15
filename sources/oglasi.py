"""oglasi.rs — обычный HTML с микроразметкой schema.org и подписанными полями."""

import datetime as dt
import html as html_mod
import re

from . import http

NAME = "oglasi"
BASE = "https://www.oglasi.rs"

ARTICLE = re.compile(r'(?=<article itemprop="itemListElement")')
# «Sobnost: <a ...><strong>Dvosoban</strong></a>» и «Kvadratura: <strong>43m2</strong>»
FIELD = r'{}:\s*(?:<a[^>]*>)?\s*<strong>([^<]+)</strong>'

ROOMS = {
    "garsonjera": 0.5, "jednosoban": 1.0, "jednoiposoban": 1.5,
    "dvosoban": 2.0, "dvoiposoban": 2.5, "trosoban": 3.0, "troiposoban": 3.5,
    "četvorosoban": 4.0, "četvorosoban i više": 4.0,
}


def _field(block, label):
    m = re.search(FIELD.format(label), block)
    return html_mod.unescape(m.group(1)).strip() if m else None


def _first(block, pattern):
    m = re.search(pattern, block)
    return m.group(1) if m else None


def fetch(url, page):
    u = http.with_params(url, "s=d", *([f"p={page}"] if page > 1 else []))
    body = http.get(u).text

    out = []
    for block in ARTICLE.split(body)[1:]:
        path = _first(block, r'href="(/oglas/[^"]+)"')
        if not path:
            continue

        price = _first(block, r'itemprop="price" content="([\d.]+)"')
        m2 = _field(block, "Kvadratura")
        rooms = (_field(block, "Sobnost") or "").lower()
        furnished = _field(block, "Opremljenost")
        heating = _field(block, "Grejanje")
        posted = _first(block, r'<time datetime="([^"]+)"')
        # Последняя ссылка-категория — это район, остальные это «Nekretnine»,
        # «Izdavanje stanova» и город.
        places = re.findall(r'itemprop="category"[^>]*>([^<]+)</a>', block)

        # «43m2» — цифру из суффикса «m2» брать нельзя, поэтому только начало строки
        m2_digits = re.match(r"\d+", m2 or "")
        m2_value = float(m2_digits.group(0)) if m2_digits else 0
        out.append({
            "id": f"{NAME}:{path.split('/')[2]}",
            "url": BASE + path,
            "price": float(price) if price else None,
            "m2": m2_value or None,          # на сайте встречается «0m2» — это «не указано»
            "rooms": ROOMS.get(rooms),
            "title": html_mod.unescape(_first(block, r'itemprop="name">([^<]+)<') or "Квартира"),
            "place": html_mod.unescape(places[-1]) if places else "",
            "description": html_mod.unescape(_first(block, r'itemprop="description">([^<]*)<') or ""),
            "image": _first(block, r'src="(https://media\.oglasi\.rs/[^"]+)"[^>]*itemprop="image"'),
            "agency": None,
            "is_agency": None,    # сайт не показывает продавца в выдаче — именно
                                  # неизвестно, а не «частник»
            "furnished": {"namešten": "yes", "nenamešten": "no"}.get((furnished or "").lower()),
            "extra": [heating] if heating else [],
            "posted": dt.datetime.fromisoformat(posted) if posted else None,
            "location": {},
        })
    return out
