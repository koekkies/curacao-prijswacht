#!/usr/bin/env python3
"""
Curaçao prijswacht - haalt met Scrapling ALLE vluchten AMS -> CUR op Google Flights op
voor de gekozen datum (met speling), inclusief KLM, TUI en Corendon.

Gebruik (lokaal of in GitHub Actions):
    python scan.py --type one_way --out 2026-12-18 --flex 3
    python scan.py --type round_trip --out 2026-12-18 --ret 2027-01-05 --flex 2

Schrijft results/latest.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ORIGIN, DEST = "AMS", "CUR"
OUT_DIR = Path(__file__).resolve().parent / "results"

# Google Flights geeft per resultaat een aria-label zoals:
#  "From 612 euros round trip total. Nonstop flight with KLM. Leaves Amsterdam Airport Schiphol
#   at 10:30 AM on Friday, December 18 and arrives at Curaçao International Airport at 3:45 PM on
#   Friday, December 18. Total duration 10 hr 15 min. ..."
RE_PRICE = re.compile(r"From\s+([\d.,]+)\s+euros?", re.I)
RE_AIRLINE = re.compile(r"flight with ([^.]+?)\.", re.I)
RE_STOPS = re.compile(r"(\d+)\s+stops?\s+flight", re.I)
RE_LEAVES = re.compile(r"Leaves .+? at (\d{1,2}:\d{2}\s?[AP]M)", re.I)
RE_ARRIVES = re.compile(r"arrives at .+? at (\d{1,2}:\d{2}\s?[AP]M)", re.I)
RE_DURATION = re.compile(r"Total duration (\d+ hr(?: \d+ min)?|\d+ min)", re.I)


def to_24h(t: str) -> str:
    try:
        return datetime.strptime(t.replace(" ", " ").strip(), "%I:%M %p").strftime("%H:%M")
    except Exception:
        return t


def build_url(dep: date, ret: date | None) -> str:
    if ret:
        q = f"Flights to {DEST} from {ORIGIN} on {dep.isoformat()} through {ret.isoformat()}"
    else:
        q = f"One way flights to {DEST} from {ORIGIN} on {dep.isoformat()}"
    params = {"q": q, "curr": "EUR", "hl": "en", "gl": "nl"}
    return "https://www.google.com/travel/flights?" + urllib.parse.urlencode(params)


def parse_label(label: str, dep: date, ret: date | None, url: str) -> dict | None:
    label = label.replace(" ", " ").replace("\xa0", " ")
    m = RE_PRICE.search(label)
    if not m:
        return None
    price = int(re.sub(r"[^\d]", "", m.group(1)))
    a = RE_AIRLINE.search(label)
    airline = a.group(1).strip().replace(" and ", ", ") if a else "Onbekend"
    if re.search(r"\bnonstop\b", label, re.I):
        stops = 0
    else:
        s = RE_STOPS.search(label)
        stops = int(s.group(1)) if s else None
    g = lambda rx: (rx.search(label).group(1) if rx.search(label) else "")
    return {
        "type": "round_trip" if ret else "one_way",
        "price": price,
        "out": dep.isoformat(),
        "ret": ret.isoformat() if ret else None,
        "airline": airline,
        "direct": stops == 0,
        "stops": stops,
        "dep_time": to_24h(g(RE_LEAVES)),
        "arr_time": to_24h(g(RE_ARRIVES)),
        "duration": g(RE_DURATION).replace(" hr", "u").replace(" min", "m"),
        "url": url,
        "source": "Google Flights",
    }


def handle_consent(page):
    """Playwright page_action: EU-cookiemelding wegklikken en wachten op resultaten."""
    try:
        if "consent." in page.url:
            for txt in ("Reject all", "Alles afwijzen", "Accept all", "Alles accepteren"):
                btn = page.get_by_role("button", name=txt)
                if btn.count():
                    btn.first.click()
                    page.wait_for_load_state("networkidle")
                    break
        page.wait_for_selector("[aria-label^='From ']", timeout=30000)
        # "Andere vluchten"/meer resultaten openklappen als die knop er is
        for txt in ("more flights", "View more flights"):
            more = page.get_by_role("button", name=re.compile(txt, re.I))
            if more.count():
                more.first.click()
                page.wait_for_timeout(2500)
                break
    except Exception:
        pass
    return page


def scan(trip_type: str, out: date, ret: date | None, flex: int, debug_dir: Path) -> tuple[list, list]:
    from scrapling.fetchers import StealthySession

    nights = (ret - out).days if ret else None
    if trip_type == "round_trip" and nights is None:
        nights = 14
    days = [out + timedelta(days=d) for d in range(-flex, flex + 1)]
    days = [d for d in days if d > date.today()]

    flights, log = [], []
    with StealthySession(headless=True) as session:
        for d in days:
            r = d + timedelta(days=nights) if trip_type == "round_trip" else None
            url = build_url(d, r)
            found = []
            try:
                page = session.fetch(url, page_action=handle_consent, network_idle=True)
                labels = page.css("[aria-label^='From ']::attr(aria-label)").getall()
                seen = set()
                for lab in labels:
                    f = parse_label(str(lab), d, r, url)
                    if not f:
                        continue
                    key = (f["price"], f["airline"], f["dep_time"], f["arr_time"])
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(f)
                if not found:
                    debug_dir.mkdir(parents=True, exist_ok=True)
                    (debug_dir / f"{d.isoformat()}.html").write_text(str(page.html_content), encoding="utf-8")
                msg = f"{d} {'→ ' + r.isoformat() if r else ''}: {len(found)} vluchten"
            except Exception as e:
                msg = f"{d}: fout {type(e).__name__}: {e}"
            print(msg, flush=True)
            log.append(msg)
            flights.extend(found)
            time.sleep(4)
    return flights, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", default="round_trip", choices=["round_trip", "one_way"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--ret", default="")
    ap.add_argument("--flex", type=int, default=3)
    a = ap.parse_args()

    out = date.fromisoformat(a.out)
    ret = date.fromisoformat(a.ret) if (a.ret and a.type == "round_trip") else None
    flex = max(0, min(a.flex, 7))

    flights, log = scan(a.type, out, ret, flex, OUT_DIR / "debug")
    tui_per_day = {}
    try:  # rechtstreeks bij TUI
        from tui import tui_scan
        tui_flights, tui_per_day, tui_log = tui_scan(a.type, out, ret, flex)
        flights.extend(tui_flights)
        log.extend(tui_log)
    except Exception as e:
        log.append(f"TUI mislukt: {type(e).__name__}: {e}")
        print(log[-1], flush=True)
    cor_per_day = {}
    try:  # rechtstreeks bij Corendon
        from corendon import corendon_scan
        cor_flights, cor_per_day, cor_log = corendon_scan(a.type, out, ret, flex)
        flights.extend(cor_flights)
        log.extend(cor_log)
    except Exception as e:
        log.append(f"Corendon mislukt: {type(e).__name__}: {e}")
        print(log[-1], flush=True)
    flights = [f for f in flights if f.get("price")]
    flights.sort(key=lambda f: (f["price"], f["out"]))
    OUT_DIR.mkdir(exist_ok=True)
    result = {
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "request": {"type": a.type, "out": a.out, "ret": a.ret, "flex": flex},
        "count": len(flights),
        "flights": flights,
        "tui_per_day": tui_per_day,
        "corendon_per_day": cor_per_day,
        "log": log,
    }
    (OUT_DIR / "latest.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Klaar: {len(flights)} vluchten", flush=True)
    if not flights:
        sys.exit(2)


if __name__ == "__main__":
    main()
