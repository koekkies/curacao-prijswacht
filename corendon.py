#!/usr/bin/env python3
"""
Corendon rechtstreeks: opent de vluchtkeuze op corendonairlines.com met Scrapling
(Cloudflare wordt opgelost) en leest per vlucht tijd, vluchtnummer, prijs en vrije stoelen,
plus de prijs per dag uit de datumbalk.

    python corendon.py --type one_way --out 2026-12-18 --flex 3
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "results"
BASE = "https://www.corendonairlines.com/flight/list"
NL_BASE = "https://www.corendon.com/nl/flights/amsterdam/curacao"
MONTHS_NL = {"jan": 1, "feb": 2, "mrt": 3, "mar": 3, "apr": 4, "mei": 5, "jun": 6, "jul": 7, "aug": 8,
             "sep": 9, "okt": 10, "nov": 11, "dec": 12}


def list_url(org: str, dst: str, d: date) -> str:
    return (f"{BASE}?Adult=1&Child=0&Infant=0&CultureCode=en&CurrencyCode=EUR"
            f"&Departure={d.strftime('%d.%m.%Y')}&Origin={org}&Destination={dst}&TripType=1")


def _num(s) -> float | None:
    try:
        v = float(str(s).replace(",", "").strip())
        return v if v > 0 else None
    except Exception:
        return None


def _iso(dmy: str, sep: str) -> str:
    try:
        return datetime.strptime(dmy, f"%d{sep}%m{sep}%Y").date().isoformat()
    except Exception:
        return ""


def parse(page, url: str) -> tuple[list[dict], dict]:
    flights, per_day = [], {}
    for it in page.css(".date-item"):
        d = _iso(it.attrib.get("data-current-date", ""), ".")
        txt = " ".join(it.css("p::text").getall()).strip()
        if not d:
            continue
        m = re.search(r"([\d.,]+)", txt)
        per_day[d] = None if ("sold" in txt.lower() or not m) else round(float(m.group(1).replace(",", "")))
    for f in page.css(".flight-item"):
        a = f.attrib
        price = _num(a.get("data-price"))
        seats = a.get("data-remaining-seats")
        out_d = _iso(a.get("data-departure-date", ""), "-")
        via = (a.get("data-via") or "").strip()
        sold = (price is None) or str(seats) == "0"
        flights.append({
            "type": "one_way",
            "price": round(price) if price else None,
            "price_exact": price,
            "sold_out": sold,
            "out": out_d,
            "ret": None,
            "airline": "Corendon (corendon.com)",
            "direct": via.lower() in ("direct", ""),
            "stops": 0 if via.lower() in ("direct", "") else 1,
            "via": "" if via.lower() in ("direct", "") else via,
            "dep_time": a.get("data-departure-time", ""),
            "arr_time": a.get("data-arrive-time", ""),
            "flight_no": (a.get("data-flight-number") or "").replace(" ", ""),
            "seats_left": int(seats) if str(seats).isdigit() else None,
            "url": url,
            "source": "Corendon.com",
        })
    return flights, per_day


def leg_scan(session, org: str, dst: str, days: list[date], log: list) -> tuple[list, dict]:
    flights, per_day = [], {}
    for d in days:
        url = list_url(org, dst, d)
        try:
            page = session.fetch(url, network_idle=True, timeout=120000, solve_cloudflare=True,
                                 wait_selector=".date-item, .flight-item", wait_selector_state="attached")
            fl, pdays = parse(page, url)
            per_day.update({k: v for k, v in pdays.items() if k not in per_day or v is not None})
            fl = [f for f in fl if f["out"] == d.isoformat()]
            flights.extend(fl)
            log.append(f"Corendon {org}→{dst} {d}: {len(fl)} vlucht(en), "
                       f"{sum(1 for f in fl if not f['sold_out'])} boekbaar")
        except Exception as e:
            log.append(f"Corendon {org}→{dst} {d}: fout {type(e).__name__}: {e}")
        print(log[-1], flush=True)
        time.sleep(3)
    return flights, per_day


def nl_parse(page, url: str, anchor: date, pax: int) -> tuple[list[dict], dict]:
    """corendon.com 4-daagse weergave: kolommen = datums, kaarten = vluchten."""
    flights, per_day = [], {}
    tables = page.css("table.flight-matrix")
    if not tables:
        return flights, per_day
    t = tables[0]  # heenvlucht
    heads = [" ".join(th.css("::text").getall()).strip() for th in t.css("thead th")]
    dates = []
    for hd in heads:
        m = re.search(r"(\d{1,2})\s+([a-z]{3})", hd.lower())
        if not m:
            dates.append(None)
            continue
        mon = MONTHS_NL.get(m.group(2))
        y = anchor.year + (1 if mon < anchor.month - 6 else 0) - (1 if mon > anchor.month + 6 else 0)
        try:
            dates.append(date(y, mon, int(m.group(1))).isoformat())
        except Exception:
            dates.append(None)
    for ci, td in enumerate(t.css("tbody tr td")):
        d = dates[ci % len(dates)] if dates else None
        if not d:
            continue
        for card in td.css(".flightcard"):
            ptxt = "".join(card.css(".price::text").getall()).strip()
            m = re.search(r"\d[\d.,]*", ptxt)
            if not m:
                continue
            price = float(m.group(0).replace(".", "").replace(",", "."))
            tm = " ".join(card.css(".time::text").getall()).strip()
            tt = re.findall(r"\d{1,2}:\d{2}", tm)
            typ = " ".join(card.css(".flight-type::text").getall()).strip().lower()
            sd = card.css(".status-dots")
            dots = sd[0].attrib.get("class", "") if sd else ""
            avail = "laatste stoelen" if "red" in dots else "beperkt aantal stoelen" if ("orange" in dots or "yellow" in dots) else ""
            direct = "direct" in typ
            flights.append({
                "type": "one_way", "price": round(price), "price_exact": price, "sold_out": False,
                "out": d, "ret": None, "airline": "Corendon (corendon.com)",
                "direct": direct, "stops": 0 if direct else 1, "via": "" if direct else "tussenstop",
                "dep_time": tt[0] if tt else "", "arr_time": tt[1] if len(tt) > 1 else "",
                "duration": "", "flight_no": "", "seats_left": None, "availability": avail,
                "pax": pax, "url": url, "source": "Corendon.com",
            })
            per_day[d] = min(per_day.get(d) or 10**9, round(price))
    return flights, per_day


def nl_scan(session, out: date, flex: int, pax: int, log: list, org="amsterdam", dst="curacao") -> tuple[list, dict]:
    flights, per_day = [], {}
    anchors = sorted({out + timedelta(days=x) for x in (-flex, 0, flex) if out + timedelta(days=x) > date.today()})
    for a in anchors:
        url = f"https://www.corendon.com/nl/flights/{org}/{dst}/{a.strftime('%Y%m%d')}?passenger={pax}&infant=0"
        try:
            page = session.fetch(url, network_idle=True, timeout=120000, solve_cloudflare=True,
                                 wait_selector=".flightcard", wait_selector_state="attached")
            fl, pd = nl_parse(page, url, a, pax)
            flights.extend(fl)
            per_day.update(pd)
            log.append(f"Corendon.com {org}→{dst} rond {a}: {len(fl)} vlucht(en)")
        except Exception as e:
            log.append(f"Corendon.com {org}→{dst} rond {a}: fout {type(e).__name__}: {e}")
        print(log[-1], flush=True)
        time.sleep(3)
    seen, uniq = set(), []
    for f in flights:
        k = (f["out"], f["dep_time"], f["price"])
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq, per_day


def corendon_scan(trip_type: str, out: date, ret: date | None, flex: int, pax: int = 1) -> tuple[list, dict, list]:
    """Hoofdbron: corendon.com (Nederlandse site, waar je boekt)."""
    from scrapling.fetchers import StealthySession
    log: list[str] = []
    with StealthySession(headless=True) as s:
        outbound, per_day = nl_scan(s, out, flex, pax, log)
        lo, hi = out - timedelta(days=flex), out + timedelta(days=flex)
        offers = [f for f in outbound if lo.isoformat() <= f["out"] <= hi.isoformat()] or outbound
        if trip_type == "round_trip":
            r = ret or (out + timedelta(days=14))
            inbound, _ = nl_scan(s, r, flex, pax, log, org="curacao", dst="amsterdam")
            combos = []
            for o in offers:
                for b in inbound:
                    if b["out"] <= o["out"]:
                        continue
                    combos.append({**o, "type": "round_trip", "ret": b["out"],
                                   "price": round(o["price_exact"] + b["price_exact"]),
                                   "price_exact": o["price_exact"] + b["price_exact"],
                                   "ret_dep_time": b["dep_time"],
                                   "airline": "Corendon (corendon.com, 2× enkele reis)"})
            combos.sort(key=lambda x: x["price"])
            offers = combos[:20]
    return offers, per_day, log


def corendon_airlines_scan(trip_type: str, out: date, ret: date | None, flex: int) -> tuple[list, dict, list]:
    """Oude bron (corendonairlines.com, andere voorraad). Niet meer standaard gebruikt."""
    from scrapling.fetchers import StealthySession

    log: list[str] = []
    out_days = [d for d in (out + timedelta(days=i) for i in range(-flex, flex + 1)) if d > date.today()]
    with StealthySession(headless=True) as s:
        outbound, per_day = leg_scan(s, "AMS", "CUR", out_days, log)
        offers = [f for f in outbound if not f["sold_out"]]
        if trip_type == "round_trip":
            r = ret or (out + timedelta(days=14))
            ret_days = [d for d in (r + timedelta(days=i) for i in range(-flex, flex + 1)) if d > out]
            inbound, _ = leg_scan(s, "CUR", "AMS", ret_days, log)
            inb = [f for f in inbound if not f["sold_out"]]
            combos = []
            for o in offers:
                for b in inb:
                    if b["out"] <= o["out"]:
                        continue
                    combos.append({**o, "type": "round_trip", "ret": b["out"],
                                   "price": round((o["price_exact"] or 0) + (b["price_exact"] or 0)),
                                   "price_exact": (o["price_exact"] or 0) + (b["price_exact"] or 0),
                                   "ret_dep_time": b["dep_time"], "ret_flight_no": b["flight_no"],
                                   "airline": "Corendon (corendon.com, 2× enkele reis)"})
            combos.sort(key=lambda x: x["price"])
            offers = combos[:20]
    return offers, per_day, log


def main():
    ap = argparse.ArgumentParser()
    cfg0 = json.loads((Path(__file__).resolve().parent / "settings.json").read_text())
    ap.add_argument("--type", default=cfg0.get("trip_type", "one_way"), choices=["round_trip", "one_way"])
    cfg = json.loads((Path(__file__).resolve().parent / "settings.json").read_text())
    ap.add_argument("--out", default=cfg.get("out_date"))
    ap.add_argument("--ret", default="")
    ap.add_argument("--flex", type=int, default=int(cfg0.get("flex_days", 3)))
    a = ap.parse_args()
    out = date.fromisoformat(a.out)
    ret = date.fromisoformat(a.ret) if (a.ret and a.type == "round_trip") else None
    fl, per_day, log = corendon_scan(a.type, out, ret, max(0, min(a.flex, 7)), int(cfg0.get("passengers", 1)))
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "corendon.json").write_text(json.dumps({
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "flights": fl, "per_day": per_day, "log": log}, ensure_ascii=False, indent=1), encoding="utf-8")
    dbg = OUT_DIR / "tui_debug"
    dbg.mkdir(parents=True, exist_ok=True)
    (dbg / "corendon.json").write_text((OUT_DIR / "corendon.json").read_text(), encoding="utf-8")
    print(f"Corendon klaar: {len(fl)} boekbare vluchten", flush=True)


if __name__ == "__main__":
    main()
