"""Источники объявлений.

Каждый модуль обязан объявить:
  NAME                — короткое имя для config.yaml и префикса ID
  fetch(url, page)    — список объявлений в общем формате (ниже)

и может объявить:
  enrich(item)        — дозагрузка деталей; вызывается только для новых
                        объявлений. Вернуть None — объявление уже неактуально.

Общий формат объявления:
  id          "источник:идентификатор" — уникален между сайтами
  url         ссылка на объявление
  price       EUR/месяц (число или None)
  m2, rooms   площадь и комнатность (число или None)
  title       заголовок
  place       район/город
  description текст объявления
  image       ссылка на фото или None
  agency      название агентства, если известно, иначе None
  is_agency   True — агентство, False — частник, None — сайт не говорит
  furnished   "yes" / "no" / None
  extra       список коротких пометок для сообщения: этаж, лифт, отопление
  posted      datetime публикации или None
  location    {"latitude": ..., "longitude": ...} или {}
"""

from . import fourzida, nekretnine, oglasi

SOURCES = {m.NAME: m for m in (fourzida, nekretnine, oglasi)}
