"""Общая HTTP-сессия для всех источников: вежливые паузы и один повтор.

Используется httpx, а не requests: nekretnine.rs отвечает промежуточным
«103 Early Hints», который http.client (и потому requests с urllib.request)
возвращает вместо финального 200 — приходит пустое тело. httpx разбирает
такие ответы корректно.
"""

import time

import httpx

# Браузерный User-Agent с нашей припиской. nekretnine.rs отдаёт 403 неизвестным
# UA, поэтому приходится представляться браузером — но приписка оставляет в логах
# сайта понятный след: кто ходит, зачем и с какой частотой.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 "
      "rent-watcher/1.0 (+personal rental alerts, 1 req/sec)")

DELAY = 1.0  # сек между запросами — не создаём нагрузку

client = httpx.Client(
    headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "sr-RS,sr;q=0.9,en;q=0.8",
    },
    timeout=30,
    follow_redirects=True,
)


def get(url):
    """GET с одним повтором — сайты отвечают не всегда с первого раза.

    Куки между запросами не сохраняются. Монитору сессия не нужна, а
    nekretnine.rs отвечает 403, если вернуть ему выданную им же куку DataDome.
    Так же по умолчанию ведёт себя curl, поэтому он и работал там, где падал
    клиент с общим cookie-jar.
    """
    for attempt in (1, 2):
        try:
            client.cookies.clear()
            r = client.get(url)
            r.raise_for_status()
            time.sleep(DELAY)
            return r
        except httpx.HTTPError as e:
            if attempt == 2:
                raise
            print(f"    повтор после ошибки: {e}", flush=True)
            time.sleep(3)


def with_params(url, *params):
    """Дописать параметры к URL, не сломав уже имеющиеся."""
    for p in params:
        url += ("&" if "?" in url else "?") + p
    return url
