#!/usr/bin/env python3
"""
KLM rechtstreeks: opent de zoekresultaten op klm.nl met Scrapling (zichtbare browser via xvfb,
want KLM blokkeert onzichtbare browsers) en leest KLM's eigen aanbod: vluchtnummer, tijden,
Economy-prijs en vrije stoelen.

    xvfb-run -a python klm.py --type one_way --out 2026-12-18 --flex 3
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "results"


def offers_url(out: date, ret: date | None, pax: int) -> str:
    conn = f"AMS:A:{out.strftime('%Y%m%d')}%3ECUR:A"
    if ret:
        conn += f"-CUR:A:{ret.strftime('%Y%m%d')}%3EAMS:A"
    return (f"https://www.klm.nl/search/offers?pax={pax}:0:0:0:0:0:0:0&cabinClass=ECONOMY"
            f"&activeConnection=0&connections={conn}&bookingFlow=LEISURE")


def parse(payload: dict, url: str, pax: int, ret: date | None) -> list[dict]:
    its = (((payload or {}).get("data") or {}).get("availableOffers") or {}).get("offerItineraries") or []
    out = []
    for it in its:
        c = it.get("activeConnection") or (it.get("connections") or [{}])[0]
        segs = c.get("segments") or []
        if not segs:
            continue
        eco = None
        for p in it.get("upsellCabinProducts") or []:
            for pc in p.get("connections") or []:
                if pc.get("cabinClass") == "ECONOMY" and (pc.get("price") or {}).get("amount"):
                    eco = pc
        if not eco:
            prices = [pc for p in it.get("flightProducts") or [] for pc in p.get("connections") or []
                      if (pc.get("price") or {}).get("amount")]
            eco = min(prices, key=lambda x: x["price"]["amount"]) if prices else None
        if not eco:
            continue
        total = float(eco["price"]["amount"])
        pp = total / max(1, int(eco.get("passengerCount") or pax))
        first, last = segs[0], segs[-1]
        num = ((first.get("marketingFlight") or {}).get("number") or "").lstrip("0")
        via = ""
        if len(segs) > 1:
            via = ((segs[0].get("destination") or {}).get("city") or {}).get("name") \
                or (segs[0].get("destination") or {}).get("code") or ""
        dur = c.get("duration")
        out.append({
            "type": "round_trip" if ret else "one_way",
            "price": round(pp),
            "price_total": round(total),
            "out": first.get("departureDateTime", "")[:10],
            "ret": ret.isoformat() if ret else None,
            "airline": "KLM (klm.nl)",
            "direct": bool(c.get("isDirect")),
            "stops": max(0, len(segs) - 1),
            "via": via if isinstance(via, str) else "",
            "dep_time": first.get("departureDateTime", "")[11:16],
            "arr_time": last.get("arrivalDateTime", "")[11:16],
            "arr_date": last.get("arrivalDateTime", "")[:10],
            "duration": f"{dur // 60}u {dur % 60}m" if isinstance(dur, int) else "",
            "flight_no": f"KL{num}" if num else "",
            "seats_left": eco.get("numberOfSeatsAvailable"),
            "pax": pax,
            "url": url,
            "source": "KLM.nl",
        })
    return out


def klm_scan(trip_type: str, out: date, ret: date | None, flex: int, pax: int = 1) -> tuple[list, dict, list]:
    from scrapling.fetchers import StealthySession

    headless = os.environ.get("HEADFUL", "") != "1"
    nights = (ret - out).days if ret else (14 if trip_type == "round_trip" else None)
    # jouw datum eerst, daarna afwisselend er net voor en net na
    order = [0] + [x for i in range(1, flex + 1) for x in (-i, i)]
    days = [out + timedelta(days=i) for i in order if out + timedelta(days=i) > date.today()]
    flights, per_day, log = [], {}, []

    for n, d in enumerate(days):
      if n:
          time.sleep(int(os.environ.get("KLM_PAUSE", "20")))
      with StealthySession(headless=headless) as s:  # nieuwe browser per datum
        if True:
            r = d + timedelta(days=nights) if trip_type == "round_trip" else None
            url = offers_url(d, r, pax)
            got = {"payload": None}

            def action(page, got=got):
                def on_resp(resp):
                    try:
                        if "SearchResultAvailableOffersQuery" in resp.url and resp.status == 200:
                            got["payload"] = resp.json()
                    except Exception:
                        pass
                page.on("response", on_resp)
                for txt in ("Akkoord", "Accepteren", "Accept"):
                    try:
                        b = page.get_by_role("button", name=re.compile(txt, re.I))
                        if b.count() and b.first.is_visible():
                            b.first.click(timeout=3000)
                            break
                    except Exception:
                        pass
                for _ in range(60):
                    if got["payload"]:
                        break
                    page.wait_for_timeout(1000)
                return page

            try:
                s.fetch(url, page_action=action, network_idle=False, timeout=150000)
                fl = parse(got["payload"], url, pax, r) if got["payload"] else []
                fl = [f for f in fl if f["out"] == d.isoformat()]
                flights.extend(fl)
                if fl:
                    per_day[d.isoformat()] = min(f["price"] for f in fl)
                log.append(f"KLM {d}{' → ' + r.isoformat() if r else ''}: "
                           f"{len(fl)} vluchten" + ("" if got["payload"] else " (geen antwoord van KLM)"))
            except Exception as e:
                log.append(f"KLM {d}: fout {type(e).__name__}: {e}")
            print(log[-1], flush=True)

    seen, uniq = set(), []
    for f in sorted(flights, key=lambda x: (x["price"], x["out"], x["dep_time"])):
        k = (f["out"], f["dep_time"], f["arr_time"], f["price"])
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq, per_day, log


def main():
    cfg = json.loads((Path(__file__).resolve().parent / "settings.json").read_text())
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", default=cfg.get("trip_type", "one_way"), choices=["round_trip", "one_way"])
    ap.add_argument("--out", default=cfg.get("out_date"))
    ap.add_argument("--ret", default=cfg.get("ret_date", ""))
    ap.add_argument("--flex", type=int, default=int(cfg.get("flex_days", 3)))
    ap.add_argument("--pax", type=int, default=int(cfg.get("passengers", 1)))
    a = ap.parse_args()
    out = date.fromisoformat(a.out)
    ret = date.fromisoformat(a.ret) if (a.ret and a.type == "round_trip") else None
    fl, per_day, log = klm_scan(a.type, out, ret, max(0, min(a.flex, 7)), a.pax)
    OUT_DIR.mkdir(exist_ok=True)
    res = {"scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "flights": fl, "per_day": per_day, "log": log}
    (OUT_DIR / "klm.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    dbg = OUT_DIR / "tui_debug"
    dbg.mkdir(parents=True, exist_ok=True)
    (dbg / "klm.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"KLM klaar: {len(fl)} vluchten", flush=True)


if __name__ == "__main__":
    main()
