#!/usr/bin/env python3
"""Proef 2: klik op een Corendon-deal-link en volg waar de zoekopdracht heen gaat."""
import json, os, re
from pathlib import Path
OUT = Path(__file__).resolve().parent / "results" / "tui_debug"
OUT.mkdir(parents=True, exist_ok=True)
info = {"requests": [], "json": []}

def action(page):
    def on_resp(r):
        try:
            if r.request.resource_type in ("xhr", "fetch", "document"):
                info["requests"].append({"u": r.url[:400], "s": r.status, "m": r.request.method, "post": (r.request.post_data or "")[:600]})
                ct = r.headers.get("content-type", "")
                if "json" in ct:
                    b = r.text()
                    if re.search(r"(price|fare|amount)", b, re.I):
                        info["json"].append({"u": r.url, "body": b[:60000]})
        except Exception:
            pass
    page.on("response", on_resp)
    page.wait_for_timeout(4000)
    for txt in ("Accept All", "Reject All"):
        try:
            b = page.get_by_role("button", name=txt, exact=True)
            if b.count() and b.first.is_visible():
                b.first.click(timeout=3000)
        except Exception:
            pass
    page.wait_for_timeout(1500)
    el = page.locator(".clickable-search.redirect-div, .redirect-div").first
    info["clicked"] = el.get_attribute("data-redirect")
    try:
        el.scroll_into_view_if_needed(timeout=5000)
        el.click(timeout=8000)
    except Exception as e:
        info["click_err"] = str(e)
    for _ in range(40):
        page.wait_for_timeout(1000)
        if "flights-from-amsterdam" not in page.url and len(info["json"]) > 0:
            break
    page.wait_for_timeout(8000)
    info["final_url"] = page.url
    info["title"] = page.title()
    info["prices"] = re.findall(r"€\s?\d[\d.,]*", page.inner_text("body"))[:60]
    page.screenshot(path=str(OUT / "cor2_result.png"), full_page=False)
    (OUT / "cor2_result.html").write_text(page.content(), encoding="utf-8")
    return page

def main():
    from scrapling.fetchers import StealthySession
    with StealthySession(headless=True) as s:
        try:
            s.fetch("https://www.corendonairlines.com/flights-from-amsterdam-to-curacao", page_action=action,
                    network_idle=True, timeout=150000, solve_cloudflare=True)
        except Exception as e:
            info["error"] = f"{type(e).__name__}: {e}"
    (OUT / "cor2_probe.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: info.get(k) for k in ("clicked", "click_err", "final_url", "title", "prices", "error")}, ensure_ascii=False)[:2500])

if __name__ == "__main__":
    main()
