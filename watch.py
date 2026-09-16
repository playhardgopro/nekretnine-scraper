#!/usr/bin/env python3
"""Мониторинг новых объявлений об аренде: 4zida.rs, nekretnine.rs, oglasi.rs.

Один запуск = один проход по всем поискам из config.yaml. Периодичность задаётся
снаружи (GitHub Actions cron). Уже показанные объявления хранятся в state.json.
"""

import argparse
import datetime as dt
import html
import json
import os
import sys

import httpx
import yaml

from sources import SOURCES

SEEN_LIMIT = 5000  # сколько ID помним; старые забываем, чтобы файл не рос вечно


def load_env():
    """Подхватить .env рядом со скриптом, если он есть.

    Уже заданные переменные не перетираем: в GitHub Actions значения приходят
    из секретов, и файла .env там нет вовсе.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


# --- фильтры ---------------------------------------------------------------

def in_range(value, lo, hi):
    if value is None:
        return lo is None and hi is None
    return (lo is None or value >= lo) and (hi is None or value <= hi)


def passes_basic(item, f):
    """Цена, площадь, комнатность — эти поля есть сразу после разбора списка."""
    return (in_range(item.get("price"), f.get("price_min"), f.get("price_max"))
            and in_range(item.get("m2"), f.get("m2_min"), f.get("m2_max"))
            and in_range(item.get("rooms"), f.get("rooms_min"), f.get("rooms_max")))


def passes_full(item, f):
    """Остальное — иногда доступно только после дозагрузки карточки."""
    if f.get("furnished") and item.get("furnished") != f["furnished"]:
        return False
    # Объявления, где продавец неизвестен, под only_private не отсеиваем:
    # лучше лишнее сообщение, чем потерянная квартира.
    if f.get("only_private") and item.get("is_agency"):
        return False
    text = f"{item.get('description', '')} {item.get('title', '')}".lower()
    if any(kw.lower() in text for kw in f.get("exclude_keywords") or []):
        return False
    return True


# --- состояние -------------------------------------------------------------

def load_state(path):
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return {"bootstrapped": [], "seen": []}


def save_state(path, state):
    # Помним только последние SEEN_LIMIT объявлений. Забытое может прийти
    # повторно, только если старое объявление поднимут наверх — а к этому
    # моменту через выдачу пройдут тысячи новых.
    state["seen"] = state["seen"][-SEEN_LIMIT:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


# --- Telegram --------------------------------------------------------------

def describe(item):
    e = html.escape
    source = item["id"].split(":", 1)[0]
    lines = [f"🆕 <b>{e(str(item.get('title') or 'Квартира'))}</b>"]

    facts = []
    price, m2 = item.get("price"), item.get("m2")
    if price:
        facts.append(f"<b>{int(price):,} €</b>".replace(",", "."))
    if m2:
        facts.append(f"{m2:g} m²")
    if item.get("rooms"):
        facts.append(f"{item['rooms']:g} комн.")
    if price and m2:
        facts.append(f"{price / m2:.0f} €/m²")
    if facts:
        lines.append("💶 " + " · ".join(facts))

    if item.get("place"):
        lines.append(f"📍 {e(str(item['place']))}")

    extra = [x for x in (item.get("extra") or []) if x]
    if item.get("furnished") == "yes":
        extra = ["с мебелью"] + extra
    if extra:
        lines.append("🏠 " + e(" · ".join(str(x) for x in extra)))

    if item.get("agency"):
        lines.append(f"👤 {e(str(item['agency']))}")
    elif item.get("is_agency") is False:
        lines.append("👤 Частное лицо")
    # is_agency is None — сайт не говорит, кто продавец; врать не будем

    posted = item.get("posted")
    if posted:
        minutes = int((dt.datetime.now(posted.tzinfo) - posted).total_seconds() // 60)
        lines.append(f"🕐 {minutes} мин назад" if minutes < 90 else f"🕐 {minutes // 60} ч назад")

    desc = (item.get("description") or "").strip()
    if desc:
        lines.append(f"\n<i>{e(desc[:400])}</i>")

    # Ссылки текстом, а не кнопками: к альбому Telegram кнопки не даёт,
    # а шаблон должен выглядеть одинаково при любом числе фотографий.
    tail = [f'<a href="{e(item["url"])}">Открыть объявление</a>']
    loc = item.get("location") or {}
    if loc.get("latitude"):
        tail.append(f'<a href="https://maps.google.com/?q={loc["latitude"]},'
                    f'{loc["longitude"]}">На карте</a>')
    tail.append(f"<code>{e(source)}</code>")
    lines.append("\n🔗 " + " · ".join(tail))
    return "\n".join(lines)


def notify(tg, item, max_photos=6):
    text = describe(item)
    api = f"https://api.telegram.org/bot{tg['token']}"

    common = {"chat_id": tg["chat_id"], "parse_mode": "HTML"}
    # В группе с темами без message_thread_id сообщение уходит в General.
    if tg.get("topic_id"):
        common["message_thread_id"] = int(tg["topic_id"])

    photos = (item.get("images") or [])[:max(2, min(max_photos, 10))]

    # Альбом: Telegram принимает от 2 до 10 снимков, подпись берётся у первого.
    if len(photos) >= 2:
        media = [{"type": "photo", "media": u} for u in photos]
        media[0] |= {"caption": text, "parse_mode": "HTML"}
        r = httpx.post(f"{api}/sendMediaGroup", timeout=60,
                       json={k: v for k, v in common.items() if k != "parse_mode"}
                            | {"media": media})
        if r.is_success:
            return
        log(f"  sendMediaGroup не прошёл ({r.text[:120]}), отправляю одним фото")

    if photos:
        r = httpx.post(f"{api}/sendPhoto", timeout=30,
                       json={**common, "photo": photos[0], "caption": text})
        if r.is_success:
            return
        log(f"  sendPhoto не прошёл ({r.text[:120]}), отправляю текстом")

    r = httpx.post(f"{api}/sendMessage", timeout=30,
                   json={**common, "text": text,
                         "link_preview_options": {"is_disabled": True}})
    # Не raise_for_status(): httpx кладёт в текст ошибки полный URL, а в нём
    # токен бота — он утёк бы в логи. Тело ответа токена не содержит.
    if not r.is_success:
        raise RuntimeError(f"Telegram sendMessage: {r.status_code} {r.text[:200]}")


# --- основной проход -------------------------------------------------------

def run_search(search, cfg, state, tg, dry_run, catchup=0):
    name = search["name"]
    source = SOURCES[search["source"]]
    filters = {**(cfg.get("filters") or {}), **(search.get("filters") or {})}
    log(f"поиск «{name}» ({search['source']})")

    items = []
    pages = catchup or search.get("max_pages", 1)
    for page in range(1, pages + 1):
        page_items = source.fetch(search["url"], page)
        if not page_items:
            break
        items += page_items
    # Пока идём по страницам, сверху могло добавиться объявление и сдвинуть
    # выдачу — тогда одна и та же карточка попадётся дважды.
    items = list({i["id"]: i for i in items}.values())
    matching = [i for i in items if passes_basic(i, filters)]
    log(f"  получено {len(items)}, подходят по цене/площади: {len(matching)}")

    seen = set(state["seen"])

    # В режиме --catchup молчаливая инициализация не нужна: мы как раз и хотим
    # увидеть всё, что уже висит на сайте.
    if catchup and name not in state["bootstrapped"]:
        state["bootstrapped"].append(name)

    # Первый запуск: запоминаем текущую выдачу молча, иначе прилетит десяток
    # сообщений о квартирах, которые висят на сайте неделю.
    if name not in state["bootstrapped"]:
        log(f"  первый запуск — запоминаю {len(matching)} объявлений без уведомлений")
        state["bootstrapped"].append(name)
        state["seen"] += [i["id"] for i in matching if i["id"] not in seen]
        return 0

    fresh = sorted((i for i in matching if i["id"] not in seen), key=lambda i: i["id"])
    log(f"  новых: {len(fresh)}")

    enrich = getattr(source, "enrich", None)
    sent = 0
    # В dry-run ничего не отправляется, поэтому защита от флуда не нужна:
    # при разборе накопившегося важно увидеть список целиком.
    limit = float("inf") if dry_run else cfg.get("max_notifications_per_run", 15)
    for item in fresh:
        if sent >= limit:
            log(f"  лимит {limit} сообщений исчерпан, остаток уйдёт следующим проходом")
            break
        full = enrich(item) if enrich else item
        state["seen"].append(item["id"])  # разобрали — больше не возвращаемся
        if full is None or not passes_full(full, filters):
            continue
        log(f"  → {full.get('price')}€ {full.get('m2')}m² {full.get('title', '')[:44]}")
        if dry_run:
            print(f"      {full['url']}")
        else:
            notify(tg, full, cfg.get("photos_per_message", 6))
        sent += 1
    return sent


def send_samples(cfg, tg, dry_run=False):
    """Проверка: по одному подходящему объявлению с каждого источника.

    С --dry-run печатает сообщения в консоль вместо отправки в Telegram.
    """
    for search in cfg["searches"]:
        source = SOURCES[search["source"]]
        filters = {**(cfg.get("filters") or {}), **(search.get("filters") or {})}
        enrich = getattr(source, "enrich", None)
        log(f"проверка «{search['name']}»")
        try:
            # Смотрим столько же страниц, сколько обычный проход: при узких
            # фильтрах на первой странице может не оказаться ничего.
            items = []
            for page in range(1, search.get("max_pages", 1) + 1):
                page_items = source.fetch(search["url"], page)
                if not page_items:
                    break
                items += page_items

            for item in items:
                if not passes_basic(item, filters):
                    continue
                full = enrich(item) if enrich else item
                if full is None or not passes_full(full, filters):
                    continue
                if dry_run:
                    print("\n" + describe(full) + f"\n    ссылка: {full['url']}\n")
                else:
                    notify(tg, full, cfg.get("photos_per_message", 6))
                    log(f"  отправлено: {full.get('price')}€ {full.get('title', '')[:50]}")
                break
            else:
                log(f"  среди {len(items)} объявлений нет подходящих под фильтры")
        except Exception as e:
            log(f"  ОШИБКА: {type(e).__name__}: {e}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--state", default="state.json")
    p.add_argument("--dry-run", action="store_true",
                   help="показать, что было бы отправлено, ничего не записывая")
    p.add_argument("--catchup", type=int, metavar="СТРАНИЦ", default=0,
                   help="разобрать накопившееся: пролистать столько страниц "
                        "вместо max_pages и показать всё подходящее, что ещё "
                        "не показывали. Лимит сообщений за проход действует, "
                        "так что запускать можно несколько раз подряд")
    p.add_argument("--test", action="store_true",
                   help="по одному подходящему объявлению с каждого сайта; "
                        "вместе с --dry-run печатает сообщения в консоль вместо "
                        "отправки. Состояние не трогает")
    args = p.parse_args()

    load_env()
    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))

    unknown = [s["source"] for s in cfg["searches"] if s["source"] not in SOURCES]
    if unknown:
        sys.exit(f"Неизвестные источники: {', '.join(unknown)}. "
                 f"Доступны: {', '.join(SOURCES)}")

    # При --dry-run в Telegram ничего не уходит, поэтому и токен не нужен.
    missing = [v for v in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not os.getenv(v)]
    if missing and not args.dry_run:
        sys.exit(f"Не заданы переменные окружения: {', '.join(missing)}. "
                 f"Положи их в .env рядом со скриптом или задай в окружении.")
    tg = {"token": os.getenv("TELEGRAM_BOT_TOKEN"),
          "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
          # Необязательный: ID темы в группе-форуме. Без него — в General.
          "topic_id": os.getenv("TELEGRAM_TOPIC_ID") or None}

    if args.test:
        send_samples(cfg, tg, args.dry_run)
        return

    state = load_state(args.state)
    total, failed = 0, []
    for search in cfg["searches"]:
        try:
            total += run_search(search, cfg, state, tg, args.dry_run, args.catchup)
        except Exception as e:
            # Один упавший сайт не должен ронять остальные.
            log(f"  ОШИБКА в поиске «{search['name']}»: {type(e).__name__}: {e}")
            if search.get("optional"):
                log("  (поиск помечен optional — это ожидаемо, тревоги не поднимаем)")
            else:
                failed.append(f"{search['name']}: {type(e).__name__}: {e}")

    if not args.dry_run:
        save_state(args.state, state)
    log(f"готово, отправлено уведомлений: {total}")

    if failed:
        # ::error:: поднимает строку на страницу запуска GitHub Actions.
        # Без этого упавший сайт теряется в логах, workflow остаётся зелёным,
        # и источник может молчать неделями незамеченным.
        for f in failed:
            print(f"::error title=Источник не ответил::{f}", flush=True)
        log(f"НЕ ОТРАБОТАЛИ ИСТОЧНИКИ: {len(failed)} из {len(cfg['searches'])}")


if __name__ == "__main__":
    main()
