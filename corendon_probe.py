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
        """js = '() => {...}'; draait in de hoofd-wereld via een scripttag, resultaat via data-attribuut."""
        try:
            page.add_script_tag(content=f"""try {{ document.documentElement.setAttribute('data-probe', JSON.stringify(({js})())); }}
                catch(e) {{ document.documentElement.setAttribute('data-probe', 'ERR '+e); }}""")
            page.wait_for_timeout(300)
            res = page.evaluate("() => document.documentElement.getAttribute('data-probe')")
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
    def shot(n):
        try:
            page.screenshot(path=str(OUT / f"cor_{n}.png"))
        except Exception:
            pass
    # bestemming: select2 openen en Curaçao kiezen
    try:
        page.locator("#destination").locator("xpath=following-sibling::span[contains(@class,'select2')]").first.click(timeout=8000)
        page.wait_for_timeout(1500)
        shot("1_dest_open")
        opts = page.locator("li.select2-results__option")
        info["steps"].append({"dest_options": opts.all_inner_texts()[:60]})
        page.locator("li.select2-results__option", has_text=re.compile("Cura", re.I)).first.click(timeout=8000)
        page.wait_for_timeout(2500)
        info["steps"].append({"dest_val": page.evaluate("() => document.querySelector('#destination').value")})
    except Exception as e:
        info["steps"].append({"dest": f"fout {e}"})
    shot("2_dest_done")
    # kalender
    try:
        page.click("#departureDate", timeout=8000)
        page.wait_for_timeout(2000)
        shot("3_cal_open")
        info["cal_html"] = page.evaluate("""() => { const c=[...document.querySelectorAll('[class*=datepicker],[class*=calendar],[class*=flatpickr],[class*=daterange]')]
            .filter(e=>e.offsetParent!==null).sort((a,b)=>b.innerHTML.length-a.innerHTML.length)[0]; return c? c.outerHTML.slice(0,6000):null; }""")
        # naar de juiste maand bladeren en de dag kiezen
        target_month = os.environ.get("COR_MONTH", "December 2026")
        for _ in range(14):
            body = page.inner_text("body")
            if re.search(target_month, body, re.I):
                break
            nxt = page.locator("[class*=next]:visible").first
            nxt.click(timeout=3000)
            page.wait_for_timeout(600)
        shot("4_cal_month")
        day = os.environ.get("COR_DAY", "18")
        cells = page.locator(f"td:visible:not(.disabled):not(.old):not(.new), [class*=day]:visible").filter(has_text=re.compile(rf"^\s*{day}\s*$"))
        info["steps"].append({"day_cells": cells.count()})
        cells.first.click(timeout=5000)
        page.wait_for_timeout(1500)
        info["steps"].append({"date_val": page.evaluate("() => document.querySelector('#departureDate').value")})
    except Exception as e:
        info["steps"].append({"cal": f"fout {e}"})
    shot("5_date_done")
    step("oneway_state", "() => ({ret_disabled: document.querySelector('#returnDate').disabled, multi: document.querySelector('#is-multi-flight').checked})")
    page.screenshot(path=str(OUT / "cor_form.png"))
    try:
        page.click("#search_flights", timeout=8000)
    except Exception as e:
        info["steps"].append({"submit": f"{e}"})
    page.wait_for_timeout(25000)
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
