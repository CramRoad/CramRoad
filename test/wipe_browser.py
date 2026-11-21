"""Render free tier, in real Chrome: the server's disk is wiped while people are editing.

With DRAGON_SECRET set, nobody should see the login page again, the project should come back
from the browsers, and a newcomer should see everyone's work. Starts its own server on 8802.
Run: python test/wipe_browser.py
"""
import os, sys, time, shutil, subprocess, tempfile, random, string, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from accounts_helper import make_account, login_script
from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PORT = 8802
BASE = f"http://localhost:{PORT}"
DATA = tempfile.mkdtemp(prefix="dragon-wipe-browser-")
SECRET = "browser-test-secret-" + "".join(random.choices(string.ascii_lowercase, k=12))
ROOM = "p-wipe" + "".join(random.choices(string.ascii_lowercase, k=6))
results = []
server = None

def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))

def wait_until(fn, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn(): return True
        except Exception:
            pass
        time.sleep(0.2)
    return False

def start():
    global server
    env = dict(os.environ, PORT=str(PORT), DATA_DIR=DATA, DRAGON_SECRET=SECRET)
    server = subprocess.Popen(["node", "server.js"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/api/ping", timeout=1); return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("server did not start")

def stop():
    global server
    if server:
        server.terminate(); server.wait(5); server = None

try:
    start()
    asha_acct, bilal_acct = make_account(BASE, "Asha"), make_account(BASE, "Bilal")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        def person(acct):
            ctx = browser.new_context(viewport={"width": 1400, "height": 900})
            ctx.add_init_script(login_script(acct))
            pg = ctx.new_page()
            pg.goto(f"{BASE}/?room={ROOM}")
            return pg
        online = lambda pg: pg.locator("#connBadge").inner_text() == "Online" and pg.locator("#syncBadge").inner_text() == "Synced"
        code = lambda pg: pg.locator("#code").input_value()

        asha, bilal = person(asha_acct), person(bilal_acct)
        check("Asha and Bilal are Online and Synced", wait_until(lambda: online(asha) and online(bilal), 15))
        asha.locator("#code").click(); asha.keyboard.press("Control+End"); asha.keyboard.type("\n<!-- ASHA-BEFORE-WIPE -->")
        check("Bilal sees Asha's text live", wait_until(lambda: "ASHA-BEFORE-WIPE" in code(bilal), 8))
        wait_until(lambda: online(asha), 8)

        print("   (server stopped and its data folder deleted, like Render does when it sleeps)")
        stop(); shutil.rmtree(DATA, ignore_errors=True)
        check("both notice the server is gone", wait_until(lambda: "Online" not in asha.locator("#connBadge").inner_text(), 20))
        bilal.locator("#code").click(); bilal.keyboard.press("Control+End"); bilal.keyboard.type("\n<!-- BILAL-WHILE-DOWN -->")
        start()

        check("both reconnect on their own: Online and Synced again", wait_until(lambda: online(asha) and online(bilal), 40),
              (asha.locator("#connBadge").inner_text(), bilal.locator("#connBadge").inner_text()))
        check("nobody was sent to the login page", asha.locator("#authScreen").is_hidden() and bilal.locator("#authScreen").is_hidden())
        check("Bilal's edit from while the server was down reached Asha", wait_until(lambda: "BILAL-WHILE-DOWN" in code(asha), 10))

        chen = person(make_account(BASE, "Chen"))
        check("a newcomer after the wipe gets the whole project from the server",
              wait_until(lambda: "ASHA-BEFORE-WIPE" in code(chen) and "BILAL-WHILE-DOWN" in code(chen), 15), code(chen)[-200:])
        check("all three screens are identical", wait_until(lambda: code(asha) == code(bilal) == code(chen), 10))
        browser.close()
finally:
    stop()
    shutil.rmtree(DATA, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
