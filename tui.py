#!/usr/bin/env python3
"""
TUI.nl rechtstreeks: opent de vluchtzoeker van tui.nl met Scrapling en leest de prijzen uit
TUI's eigen zoekresultaten (dezelfde gegevens die je op tui.nl ziet), plus de prijs per dag.

    python tui.py --type one_way --out 2026-12-18 --flex 3
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "results"


def search_url(dep: date, ret: date | None, pax: int = 1) -> str:
    p = {
        "flyingFrom[]": "AMS", "flyingTo[]": "CUR", "depDate": dep.isoformat(),
        "adults": str(pax), "children": "0", "childAge": "", "choiceSearch": "true",
        "searchType": "pricegrid", "nearByAirports": "true", "currency": "EUR",
        "isOneWay": "false" if ret else "true",
    }
    if ret:
        p["returnDate"] = ret.isoformat()
    return "https://www.tui.nl/flight/nl/search?" + urllib.parse.urlencode(p)


def _hhmm(iso: str) -> str:
    return iso[11:16] if iso and len(iso) >= 16 else ""


def _dur(mins) -> str:
    try:
        m = int(mins)
        return f"{m // 60}u {m % 60}m"
    except Exception:
        return ""


def parse_offers(payload: dict, url: str, trip_type: str) -> list[dict]:
    offers = (((payload or {}).get("data") or {}).get("getSearchResults") or {}).get("flightOffers") or []
    out = []
    for o in offers:
        dirs = o.get("directions") or []
        ob = next((d for d in dirs if d.get("type") == "outbound"), dirs[0] if dirs else None)
        ib = next((d for d in dirs if d.get("type") in ("inbound", "return")), None)
        if not ob:
            continue
        price = (o.get("priceDetails") or {}).get("pricePerPerson")
        if price is None:
            continue
        st = (ob.get("stopoverType") or {})
        direct = st.get("flightType") in (None, "direct", "non_stop", "nonstop")
        via = st.get("text") or ""
        seg = (ob.get("segments") or [{}])[0]
        out.append({
            "type": "round_trip" if (trip_type == "round_trip" and ib) else "one_way",
            "price": round(float(price)),
            "price_exact": float(price),
            "out": ob.get("departureTime", "")[:10],
            "ret": ib.get("departureTime", "")[:10] if ib else None,
            "airline": "TUI (tui.nl)",
            "direct": bool(direct),
            "stops": 0 if direct else 1,
            "via": via,
            "dep_time": _hhmm(ob.get("departureTime", "")),
            "arr_time": _hhmm(ob.get("arrivalTime", "")),
            "duration": _dur(ob.get("duration")),
            "flight_no": f"OR{seg.get('flightNumber') or ob.get('id') or ''}",
            "seats_left": ob.get("availableSeats"),
            "url": url,
            "source": "TUI.nl",
            "pax": None,
        })
    return out


def tui_scan(trip_type: str, out: date, ret: date | None, flex: int, pax: int = 1) -> tuple[list, dict, list]:
    """Geeft (vluchten, prijs-per-dag, log)."""
    from scrapling.fetchers import StealthySession

    nights = (ret - out).days if ret else (14 if trip_type == "round_trip" else None)
    days = [d for d in (out + timedelta(days=i) for i in range(-flex, flex + 1)) if d > date.today()]
    flights, per_day, log = [], {}, []

    with StealthySession(headless=True) as s:
        for d in days:
            r = d + timedelta(days=nights) if trip_type == "round_trip" else None
            url = search_url(d, r, pax)
            captured = {"results": [], "carousel": []}

            def action(page, captured=captured):
                def on_resp(resp):
                    try:
                        u = resp.url
                        if "flight-search-results/graphql" in u:
                            j = resp.json()
                            if (((j or {}).get("data") or {}).get("getSearchResults")):
                                captured["results"].append(j)
                        elif "flight-alternative-dates-carousel" in u:
                            captured["carousel"].append(resp.json())
                    except Exception:
                        pass
                page.on("response", on_resp)
                for txt in ("Weigeren", "Accepteer cookies"):
                    try:
                        b = page.get_by_role("button", name=txt)
                        if b.count():
                            b.first.click(timeout=3000)
                            break
                    except Exception:
                        pass
                try:
                    page.reload(wait_until="networkidle", timeout=60000)
                except Exception:
                    pass
                for _ in range(20):
                    if captured["results"]:
                        break
                    page.wait_for_timeout(1000)
                return page

            n = 0
            try:
                s.fetch(url, page_action=action, network_idle=True, timeout=90000)
                for res in captured["results"]:
                    fl = parse_offers(res, url, trip_type)
                    flights.extend(fl)
                    n += len(fl)
                for car in captured["carousel"]:
                    for row in car or []:
                        try:
                            per_day[row["departureDate"]] = round(float(row["pricePerAdult"]))
                        except Exception:
                            pass
                msg = f"TUI {d}{' → ' + r.isoformat() if r else ''}: {n} vluchten"
            except Exception as e:
                msg = f"TUI {d}: fout {type(e).__name__}: {e}"
            print(msg, flush=True)
            log.append(msg)
            time.sleep(3)

    seen, uniq = set(), []
    for f in sorted(flights, key=lambda x: (x["price"], x["out"], x["dep_time"])):
        k = (f["out"], f["ret"], f["dep_time"], f["price"])
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq, per_day, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", default="round_trip", choices=["round_trip", "one_way"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--ret", default="")
    ap.add_argument("--flex", type=int, default=3)
    a = ap.parse_args()
    out = date.fromisoformat(a.out)
    ret = date.fromisoformat(a.ret) if (a.ret and a.type == "round_trip") else None
    fl, per_day, log = tui_scan(a.type, out, ret, max(0, min(a.flex, 7)))
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "tui.json").write_text(json.dumps({
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "flights": fl, "per_day": per_day, "log": log}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"TUI klaar: {len(fl)} vluchten", flush=True)


if __name__ == "__main__":
    main()
