#!/usr/bin/env python3
"""
Voegt de round_trip-vluchten van meerdere retourscans (elk een latest.json van scan.py)
samen tot één bestand met dezelfde opbouw als latest.json.

    python merge_rt.py results/latest_rt.json rt_2026-12-17.json rt_2026-12-18.json

Overschrijft het doelbestand niet als er geen enkele retourvlucht is gevonden,
zodat een mislukte ronde de vorige goede uitkomst laat staan.
"""
import json
import sys
from pathlib import Path

PER_DAY_KEYS = ("tui_per_day", "corendon_per_day", "klm_per_day")


def merge_per_day(dicts):
    out = {}
    for d in dicts:
        for k, v in (d or {}).items():
            if v is None:
                out.setdefault(k, None)  # uitverkocht, tenzij een andere scan wel een prijs heeft
            elif out.get(k) is None or v < out[k]:
                out[k] = v
    return dict(sorted(out.items()))


def main():
    if len(sys.argv) < 3:
        sys.exit("gebruik: merge_rt.py DOEL.json SCAN1.json [SCAN2.json ...]")
    target, sources = Path(sys.argv[1]), [Path(p) for p in sys.argv[2:]]
    scans = []
    for p in sources:
        try:
            scans.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"overgeslagen: {p} ({e})")
    if not scans:
        sys.exit("geen retourscans om samen te voegen")

    flights, log, seen = [], [], set()
    for sc in scans:
        req = sc.get("request") or {}
        tag = f"[{req.get('out')} → {req.get('ret')}]"
        rt = [f for f in sc.get("flights") or [] if f.get("type") == "round_trip"]
        dropped = len(sc.get("flights") or []) - len(rt)
        for f in rt:
            k = (f.get("out"), f.get("ret"), f.get("airline"), f.get("dep_time"),
                 f.get("price"), f.get("source"))
            if k not in seen:
                seen.add(k)
                flights.append(f)
        log += [f"{tag} {line}" for line in sc.get("log") or []]
        if dropped:
            log.append(f"{tag} {dropped} vlucht(en) zonder retour weggelaten")
    flights.sort(key=lambda f: (f.get("price") or 10**9, f.get("out") or "", f.get("ret") or ""))

    if not flights:
        print("geen retourvluchten gevonden; vorig bestand blijft staan")
        return

    reqs = [sc.get("request") or {} for sc in scans]
    rets = sorted({r.get("ret") for r in reqs if r.get("ret")})
    result = {
        "scanned_at": max(sc.get("scanned_at") or "" for sc in scans),
        "request": {
            "type": "round_trip",
            "out": [r.get("out") for r in reqs],
            "ret": rets[0] if len(rets) == 1 else rets,
            "flex": reqs[0].get("flex", 0),
            "pax": reqs[0].get("pax", 1),
        },
        "count": len(flights),
        "flights": flights,
        **{k: merge_per_day(sc.get(k) for sc in scans) for k in PER_DAY_KEYS},
        "log": log,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{target}: {len(flights)} retourvluchten uit {len(scans)} scan(s)")


if __name__ == "__main__":
    main()
