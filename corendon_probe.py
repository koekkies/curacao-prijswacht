#!/usr/bin/env python3
"""Proef: vult het zoekformulier op corendonairlines.com in en bewaart wat er terugkomt."""
import json
import os
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent / "results" / "tui_debug"
OUT.mkdir(parents=True, exist_ok=True)
DATE = os.environ.get("COR_DATE", "18.12.2026")
info = {"steps": [], "json": [], "requests": []}


def action(page):
    def on_resp(r):
        try:
            if r.request.resource_type in ("xhr", "fetch", "document"):
                info["requests"].append({"u": r.url[:300], "s": r.status, "m": r.request.method,
                                         "post": (r.request.post_data or "")[:500]})
                ct = r.headers.get("content-type", "")
                if "json" in ct or "html" in ct and r.request.resource_type in ("xhr", "fetch"):
                    b = r.text()
                    if re.search(r"(price|fare|amount|€|EUR)", b, re.I):
                        info["json"].append({"u": r.url, "body": b[:40000]})
        except Exception:
            pass

    page.on("response", on_resp)

    def step(name, js=None, wait=1500):
        try:
            res = page.evaluate(js) if js else None
            info["steps"].append({name: res})
        except Exception as e:
            info["steps"].append({name: f"fout {e}"})
        page.wait_for_timeout(wait)

    for txt in ("Accept", "Allow all", "Accept all", "Alle cookies"):
        try:
            b = page.get_by_role("button", name=re.compile(txt, re.I))
            if b.count():
                b.first.click(timeout=3000)
                break
        except Exception:
            pass
    page.wait_for_timeout(2000)
    step("jquery", "() => typeof window.jQuery")
    step("origin", "() => { const $=window.jQuery; $('#origin').val('AMS').trigger('change'); $('#origin').trigger({type:'select2:select', params:{data:{id:'AMS'}}}); return $('#origin').val(); }", 4000)
    step("dest_opts", "() => [...document.querySelectorAll('#destination option')].map(o=>o.value+':'+o.textContent.trim()).slice(0,40)")
    step("dest", "() => { const $=window.jQuery; $('#destination').prop('disabled',false).val('CUR').trigger('change'); $('#destination').trigger({type:'select2:select', params:{data:{id:'CUR'}}}); return $('#destination').val(); }", 3000)
    step("date", f"""() => {{ const $=window.jQuery; const el=$('#departureDate');
        try {{ el.datepicker('setDate', '{DATE}'); }} catch(e) {{}}
        el.val('{DATE}').trigger('change'); return el.val(); }}""", 1500)
    step("oneway_state", "() => ({ret_disabled: document.querySelector('#returnDate').disabled, multi: document.querySelector('#is-multi-flight').checked})")
    page.screenshot(path=str(OUT / "cor_form.png"))
    try:
        with page.expect_navigation(timeout=60000):
            page.click("#search_flights")
    except Exception as e:
        info["steps"].append({"submit": f"{e}"})
    page.wait_for_timeout(15000)
    info["final_url"] = page.url
    info["title"] = page.title()
    info["prices"] = (re.findall(r"€\s?\d[\d.,]*", page.inner_text("body")) or [])[:60]
    page.screenshot(path=str(OUT / "cor_result.png"), full_page=True)
    (OUT / "cor_result.html").write_text(page.content(), encoding="utf-8")
    return page


def main():
    from scrapling.fetchers import StealthySession
    with StealthySession(headless=True) as s:
        try:
            s.fetch("https://www.corendonairlines.com/flights-from-amsterdam-to-curacao",
                    page_action=action, network_idle=True, timeout=120000, solve_cloudflare=True)
        except Exception as e:
            info["error"] = f"{type(e).__name__}: {e}"
    (OUT / "cor_probe.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: info.get(k) for k in ("steps", "final_url", "title", "prices", "error")}, ensure_ascii=False)[:3000])


if __name__ == "__main__":
    main()
