"""One person, many tabs: each teammate must appear once (one name, one cursor, one dot).

Asha opens the room in 3 tabs of the same browser, Bilal in 1. Asha switches tabs, reloads,
closes tabs; nobody may ever see Asha twice, and nobody sees their own other tabs as a
teammate. Needs the sync server (npm start). Run:
  python test/presence_scenario.py [http://localhost:8787]
"""
import os, sys, time, random, string
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from accounts_helper import make_account, login_script
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8787"
ROOM = "p-pres" + "".join(random.choices(string.ascii_lowercase, k=6))
results = []

def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))

def wait_until(fn, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn(): return True
        except Exception:
            pass
        time.sleep(0.2)
    try: return bool(fn())
    except Exception: return False

people = lambda pg: pg.locator("#collabPeople .person-chip span").all_inner_texts()
carets = lambda pg: pg.locator(".remote-caret span").all_inner_texts()
dots = lambda pg: pg.locator(".presence-dot").count()
me_btn = lambda pg: pg.locator("#renameMe").inner_text()
online = lambda pg: pg.locator("#connBadge").inner_text() == "Online" and pg.locator("#syncBadge").inner_text() == "Synced"

def caret_top(pg):
    """Pixel top of the (single) remote caret, or None."""
    loc = pg.locator(".remote-caret")
    return loc.first.evaluate("e => parseFloat(e.style.top)") if loc.count() == 1 else None

with sync_playwright() as p:
    browser = p.chromium.launch()
    asha_acct, bilal_acct = make_account(BASE, "Asha"), make_account(BASE, "Bilal")
    actx = browser.new_context(viewport={"width": 1400, "height": 900})
    actx.add_init_script(login_script(asha_acct))
    bctx = browser.new_context(viewport={"width": 1400, "height": 900})
    bctx.add_init_script(login_script(bilal_acct))
    url = f"{BASE}/?room={ROOM}"
    js_errors = []
    for ctx in (actx, bctx):
        ctx.on("page", lambda pg: pg.on("pageerror", lambda e: js_errors.append(str(e))))

    bilal = bctx.new_page(); bilal.goto(url)
    asha_tabs = []
    for _ in range(3):
        pg = actx.new_page(); pg.goto(url); asha_tabs.append(pg)
    check("everyone is Online and Synced", wait_until(lambda: all(online(pg) for pg in asha_tabs + [bilal]), 20))
    for pg in asha_tabs + [bilal]:
        pg.locator("#code").click()

    # ------------------------------------------------------------------ 1. one person, one entry
    print("\n== 1. Asha has 3 tabs open")
    check("Bilal sees Asha once in the people bar", wait_until(lambda: people(bilal) == ["Asha"], 8), people(bilal))
    check("Bilal sees one cursor for Asha", wait_until(lambda: carets(bilal) == ["Asha"], 8), carets(bilal))
    check("Bilal's Explorer shows one dot for Asha", wait_until(lambda: dots(bilal) == 1, 8), dots(bilal))
    for i, pg in enumerate(asha_tabs):
        check(f"Asha's tab {i + 1} shows only Bilal, never herself", wait_until(lambda: people(pg) == ["Bilal"] and carets(pg) == ["Bilal"], 8), (people(pg), carets(pg)))
    check("Asha's 'You' button says she has 3 tabs", wait_until(lambda: "3 tabs" in me_btn(asha_tabs[0]), 8), me_btn(asha_tabs[0]))

    # ------------------------------------------------------------------ 2. cursor follows the tab she uses
    print("\n== 2. The cursor follows the tab Asha is using")
    a2 = asha_tabs[1]
    a2.bring_to_front(); a2.locator("#code").click(); a2.keyboard.press("Control+End")
    a2.keyboard.type("\n<!-- asha in tab 2 -->\n<!-- line two -->")
    check("Bilal gets her text", wait_until(lambda: "line two" in bilal.locator("#code").input_value(), 8))
    check("Bilal's Asha cursor moved to the end, where tab 2 typed", wait_until(lambda: (caret_top(bilal) or 0) > 200, 8), caret_top(bilal))
    low = caret_top(bilal)
    a1 = asha_tabs[0]
    a1.bring_to_front(); a1.locator("#code").click(); a1.keyboard.press("Control+Home")
    check("she clicks at the top in tab 1: Bilal's one Asha cursor jumps there", wait_until(lambda: caret_top(bilal) is not None and caret_top(bilal) < (low or 0), 8), (caret_top(bilal), low))
    check("still exactly one Asha cursor", carets(bilal) == ["Asha"], carets(bilal))

    # ------------------------------------------------------------------ 3. who wrote this
    print("\n== 3. Who wrote this")
    a1.keyboard.type("<!-- asha in tab 1 -->\n")
    check("Bilal gets the text from tab 1", wait_until(lambda: "asha in tab 1" in bilal.locator("#code").input_value(), 8))
    bilal.locator("#authorsBtn").click()
    legend = lambda: bilal.locator("#authorLegend .al-item").all_inner_texts()
    check("the legend lists Asha once, though she typed from two tabs", wait_until(lambda: sum(1 for t in legend() if t.startswith("Asha")) == 1, 8), legend())
    bilal.locator("#authorsBtn").click()

    # ------------------------------------------------------------------ 4. reload and close
    print("\n== 4. Reloading and closing tabs")
    asha_tabs[2].reload()
    check("tab 3 reconnects after the reload", wait_until(lambda: online(asha_tabs[2]), 15))
    time.sleep(1.5)
    check("after the reload Bilal still sees Asha once (no ghost cursor)", wait_until(lambda: people(bilal) == ["Asha"] and len(carets(bilal)) <= 1, 8), (people(bilal), carets(bilal)))
    asha_tabs[2].close(); asha_tabs[1].close()
    check("after she closes 2 tabs, her last tab no longer mentions other tabs", wait_until(lambda: "tabs" not in me_btn(a1), 10), me_btn(a1))
    check("Bilal still sees Asha once", people(bilal) == ["Asha"], people(bilal))
    a1.close()
    check("when she closes her last tab, she disappears for Bilal", wait_until(lambda: people(bilal) == [] and carets(bilal) == [], 10), (people(bilal), carets(bilal)))
    check("no JavaScript errors on any page", not js_errors, js_errors[:3])
    browser.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
