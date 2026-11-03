"""Route en reizigers uit settings.json (één plek voor alle scrapers)."""
from __future__ import annotations

import json
from pathlib import Path

_CFG = json.loads((Path(__file__).resolve().parent / "settings.json").read_text())

ORIGIN = _CFG.get("origin", "AMS").upper()
DEST = _CFG.get("dest", "CUR").upper()
ADULTS = int(_CFG.get("adults", _CFG.get("passengers", 1)))
CHILDREN = int(_CFG.get("children", 0))
CHILD_AGES = [int(x) for x in _CFG.get("child_ages", [])][:CHILDREN]
PAX = ADULTS + CHILDREN

CITY_SLUG = {"AMS": "amsterdam", "CUR": "curacao"}
ORIGIN_SLUG = CITY_SLUG.get(ORIGIN, ORIGIN.lower())
DEST_SLUG = CITY_SLUG.get(DEST, DEST.lower())
