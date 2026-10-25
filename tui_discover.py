#!/usr/bin/env python3
"""Verkenning van tui.nl: screenshots, formuliervelden en netwerkverkeer, zodat de TUI-scraper
gebouwd kan worden. Schrijft alles naar results/tui_debug/."""
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent / "results" / "tui_debug"
import os
OUT.mkdir(parents=True, exist_ok=True)

CANDIDATES = json.loads(os.environ["CANDIDATES"]) if os.environ.get("CANDIDATES") else {
    "home": "https://www.tui.nl/vliegtickets/",
    "search_a": "https://www.tui.nl/flight/nl/search?flyingFrom%5B%5D=AMS&flyingTo%5B%5D=CUR&depDate=2026-12-18&adults=1&isOneWay=true",
}

net = {}


def make_action(name):
    def action(page):
        reqs = []
        page.on("request", lambda r: reqs.append({"m": r.method, "u": r.url, "t": r.resource_type}))
        resp = []

        def on_resp(r):
            try:
                ct = r.headers.get("content-type", "")
                if "json" in ct and r.request.resource_type in ("xhr", "fetch"):
                    body = r.text()
                    if "gql" in r.url or "graphql" in r.url or re.search(r"(price|prijs|amount|fare|offer)", body, re.I):
                        resp.append({"u": r.url, "status": r.status, "body": body[:60000]})
            except Exception:
                pass

        page.on("response", on_resp)
        # cookiemelding
        for txt in ("Accepteren", "Alles accepteren", "Akkoord", "Accept all", "Accepteer alle cookies", "Accept", "Agree", "Weigeren", "Reject"):
            try:
                b = page.get_by_role("button", name=re.compile(txt, re.I))
                if b.count():
                    b.first.click(timeout=3000)
                    break
            except Exception:
                pass
        page.wait_for_timeout(2000)
        try:
            page.reload(wait_until="networkidle", timeout=45000)
        except Exception:
            pass
        page.wait_for_timeout(int(os.environ.get("WAIT_MS", "9000")))
        for txt in (os.environ.get("CLICK", "") or "").split("|"):
            if not txt:
                continue
            try:
                b = page.get_by_role("button", name=re.compile(txt, re.I))
                if b.count():
                    b.first.click(timeout=5000)
                    page.wait_for_timeout(int(os.environ.get("WAIT_MS", "9000")))
            except Exception:
                pass
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
        info = page.evaluate("""() => {
          const pick = el => ({tag: el.tagName, type: el.type||'', name: el.name||'', id: el.id||'',
            ph: el.placeholder||'', aria: el.getAttribute('aria-label')||'',
            test: el.getAttribute('data-test-id')||el.getAttribute('data-testid')||'',
            text: (el.innerText||el.value||'').trim().slice(0,60)});
          return {
            url: location.href, title: document.title,
            inputs: [...document.querySelectorAll('input,select,button,[role=button],[role=combobox]')].slice(0,150).map(pick),
            links: [...document.querySelectorAll('a[href]')].map(a=>a.href).filter(h=>/flight|vlucht|search|zoek|book|offer|ibe|select/i.test(h)).slice(0,150),
            prices: (document.body.innerText.match(/€\\s?\\d[\\d.,]*/g)||[]).slice(0,40)
          };
        }""")
        info["requests"] = [r for r in reqs if r["t"] in ("xhr", "fetch", "document")][:200]
        info["json_with_prices"] = resp[:40]
        net[name] = info
        return page
    return action


def main():
    from scrapling.fetchers import StealthySession
    with StealthySession(headless=True) as s:
        for name, url in CANDIDATES.items():
            try:
                p = s.fetch(url, page_action=make_action(name), network_idle=True, timeout=120000, solve_cloudflare=True)
                (OUT / f"{name}.html").write_text(str(p.html_content), encoding="utf-8")
                print(name, "->", net.get(name, {}).get("url"), net.get(name, {}).get("title"), flush=True)
            except Exception as e:
                print(name, "fout", type(e).__name__, e, flush=True)
                net[name] = {"error": f"{type(e).__name__}: {e}"}
    (OUT / "discover.json").write_text(json.dumps(net, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
