#!/usr/bin/env python3
"""Proef: KLM-zoekopdracht met zichtbare browser (xvfb). Bewaart screenshots en de JSON-antwoorden."""
import json
import os
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent / "results" / "tui_debug"
OUT.mkdir(parents=True, exist_ok=True)
DATE = os.environ.get("KLM_DATE", "20261218")
PAX = int(os.environ.get("KLM_PAX", "3"))
URL = (f"https://www.klm.nl/search/offers?pax={PAX}:0:0:0:0:0:0:0&cabinClass=ECONOMY&activeConnection=0"
       f"&connections=AMS:A:{DATE}%3ECUR:A&bookingFlow=LEISURE")
info = {"steps": [], "gql": [], "requests": []}


def action(page):
    def on_resp(r):
        try:
            u = r.url
            if r.request.resource_type in ("xhr", "fetch"):
                info["requests"].append({"u": u[:300], "s": r.status})
            if "/gql/" in u:
                op = re.search(r"operationName=([A-Za-z]+)", u)
                body = r.text()
                info["gql"].append({"op": op.group(1) if op else u[-80:], "s": r.status, "len": len(body),
                                    "body": body[:80000] if re.search(r"price|amount|offer", body, re.I) else ""})
        except Exception:
            pass

    page.on("response", on_resp)

    def shot(n):
        try:
            page.screenshot(path=str(OUT / f"klm_{n}.png"))
        except Exception:
            pass

    page.wait_for_timeout(5000)
    for txt in ("Akkoord", "Accepteren", "Alles accepteren", "Accept"):
        try:
            b = page.get_by_role("button", name=re.compile(txt, re.I))
            if b.count() and b.first.is_visible():
                b.first.click(timeout=3000)
                info["steps"].append(f"cookie: {txt}")
                break
        except Exception:
            pass
    page.wait_for_timeout(25000)
    shot("1_loaded")
    info["steps"].append(f"url1 {page.url}")
    if "/search/advanced" in page.url or "offers" not in page.url:
        # enkele reis kiezen
        try:
            page.get_by_role("button", name=re.compile("Retourreis", re.I)).first.click(timeout=5000)
            page.wait_for_timeout(1000)
            page.get_by_text(re.compile("^Enkele reis$", re.I)).first.click(timeout=5000)
            info["steps"].append("enkele reis gekozen")
        except Exception as e:
            info["steps"].append(f"enkele reis fout: {e}")
        page.wait_for_timeout(2000)
        shot("2_oneway")
        try:
            btn = page.locator("button[type=submit]").last
            btn.click(timeout=8000)
            info["steps"].append("zoekknop geklikt")
        except Exception as e:
            info["steps"].append(f"zoekknop fout: {e}")
        for _ in range(45):
            page.wait_for_timeout(1000)
            if any(g["body"] and "Offer" in g["op"] for g in info["gql"]):
                break
        page.wait_for_timeout(8000)
    shot("3_result")
    info["final_url"] = page.url
    info["prices"] = re.findall(r"€\s?\d[\d.,]*|\d[\d.,]*\s?€|EUR\s?\d[\d.,]*", page.inner_text("body"))[:40]
    (OUT / "klm_result.html").write_text(page.content(), encoding="utf-8")
    return page


def main():
    from scrapling.fetchers import StealthySession
    headless = os.environ.get("HEADFUL", "") != "1"
    with StealthySession(headless=headless) as s:
        try:
            s.fetch(URL, page_action=action, network_idle=False, timeout=180000, solve_cloudflare=False)
        except Exception as e:
            info["error"] = f"{type(e).__name__}: {e}"
    (OUT / "klm_probe.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: info.get(k) for k in ("steps", "final_url", "prices", "error")}, ensure_ascii=False)[:3000])
    print("gql ops:", [(g["op"], g["s"], g["len"]) for g in info["gql"]])


if __name__ == "__main__":
    main()
