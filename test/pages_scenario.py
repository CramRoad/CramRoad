"""The page on a static host (like GitHub Pages) + the DRAGON server somewhere else (like Render).

A plain static web server stands in for GitHub Pages: it serves only index.html and sw.js under
/dragon-editor/, so /api/ping there answers 404 like it does on github.io. The DRAGON sync server
runs separately. Three people join one room through the Share link, the ⚙ Server button and the
page's plain address. Needs the sync server (npm start). Run:
  python test/pages_scenario.py [http://localhost:8787] [chrome]
"""
import sys, os, time, shutil, tempfile, threading, functools
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else "http://localhost:8787"
CHROME = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_WS = BASE.replace("http://", "ws://").replace("https://", "wss://").rstrip("/") + "/ws"
SERVER_HOST = urlparse(BASE).netloc
PASSWORD = "dragon-fire-2026"
results = []

def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (("  -> " + str(detail)[:220]) if detail and not cond else ""))

def wait_until(fn, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn(): return True
        except Exception:
            pass
        time.sleep(0.15)
    return False

# ---------------------------------------------------------------- the "GitHub Pages" copy
site = tempfile.mkdtemp(prefix="dragon-pages-")
os.makedirs(os.path.join(site, "dragon-editor"))
for name in ("index.html", "sw.js"):
    shutil.copy(os.path.join(ROOT, name), os.path.join(site, "dragon-editor", name))

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
static = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=site))
threading.Thread(target=static.serve_forever, daemon=True).start()
PAGES = f"http://127.0.0.1:{static.server_address[1]}/dragon-editor/"
print("static copy (stands in for GitHub Pages):", PAGES)
print("DRAGON sync server:", SERVER_WS)

INIT = "if (window === window.top) { window.__appErrors = []; addEventListener('error', e => window.__appErrors.push(String(e.message))); }"
STAMP = str(int(time.time()))

with sync_playwright() as p:
    launch = {"args": ["--no-sandbox"]}
    if CHROME: launch["executable_path"] = CHROME
    browser = p.chromium.launch(**launch)
    pages = []

    def person():
        # Share link copies to the clipboard; headless Chrome needs the permission granted.
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, permissions=["clipboard-read", "clipboard-write"])
        ctx.add_init_script(INIT)
        pg = ctx.new_page()
        pages.append(pg)
        return pg

    home = lambda pg: pg.locator("#authHome").inner_text()
    conn = lambda pg: pg.locator("#connBadge").inner_text()
    online = lambda pg: conn(pg) == "Online" and pg.locator("#syncBadge").inner_text() == "Synced"
    code = lambda pg: pg.locator("#code").input_value()
    people = lambda pg: pg.locator("#collabPeople").inner_text()

    def sign_up(pg, name):
        pg.locator("#authName").fill(name)
        pg.locator("#authEmail").fill(f"{name.lower()}.{STAMP}@example.com")
        pg.locator("#authPassword").fill(PASSWORD)
        pg.locator("#authSubmit").click()
        return wait_until(lambda: pg.locator("#authScreen").is_hidden(), 15)

    def type_end(pg, text):
        pg.locator("#code").click()
        pg.keyboard.press("Control+End")
        pg.keyboard.type(text)

    def share_link(pg):
        pg.locator(".toast").evaluate_all("els => els.forEach(e => e.remove())")
        pg.locator("#shareRoom").click()
        time.sleep(0.5)
        toasts = pg.locator(".toast").all_inner_texts()
        return next((t.split("copied: ", 1)[1].strip() for t in toasts if "copied: " in t), "")

    # ------------------------------------------------------------------ 1. plain static copy
    print("\n== 1. The static copy alone has no sync server")
    asha = person()
    asha.goto(PAGES)
    check("the login page comes first", wait_until(lambda: asha.locator("#authScreen").is_visible(), 6))
    check("on its own it offers an account on this device (no server there)",
          wait_until(lambda: home(asha) == "Account on this device", 6), home(asha))

    # ------------------------------------------------------------------ 2. link with ?server=
    print("\n== 2. Asha opens the static copy with ?server= pointing at the DRAGON server")
    asha.goto(PAGES + "?server=" + quote(SERVER_WS, safe=""))
    check("the login page says the account is on the DRAGON server, and which one",
          wait_until(lambda: home(asha) == "Account on the DRAGON server at " + SERVER_HOST, 8), home(asha))
    check("Asha creates an account from the static copy", sign_up(asha, "Asha"))
    check("Asha is Online and Synced through the separate server", wait_until(lambda: online(asha), 15),
          (conn(asha), asha.locator("#syncBadge").inner_text()))
    room = parse_qs(urlparse(asha.url).query).get("room", [""])[0]
    check("the address bar keeps the room and the server", room.startswith("p-") and "server=" in asha.url, asha.url)
    type_end(asha, "\n<!-- @@ASHA-PAGES@@ -->")
    check("Asha's edit is acknowledged by the server", wait_until(lambda: online(asha), 10))
    link = share_link(asha)
    check("Share link points at the static copy, the room and the server",
          link.startswith(PAGES + "?room=" + room) and ("server=" + quote(SERVER_WS, safe="")) in link, link)

    # ------------------------------------------------------------------ 3. teammate joins by link
    print("\n== 3. Bilal opens Asha's link")
    bilal = person()
    bilal.goto(link)
    check("Bilal's login page names the same server",
          wait_until(lambda: home(bilal) == "Account on the DRAGON server at " + SERVER_HOST, 8), home(bilal))
    check("Bilal creates an account", sign_up(bilal, "Bilal"))
    check("Bilal is Online in the same room", wait_until(lambda: online(bilal), 15)
          and parse_qs(urlparse(bilal.url).query).get("room", [""])[0] == room, (conn(bilal), bilal.url))
    check("Bilal sees Asha's edit", wait_until(lambda: "@@ASHA-PAGES@@" in code(bilal), 10))
    type_end(bilal, "\n<!-- @@BILAL-PAGES@@ -->")
    check("Asha sees Bilal's edit live", wait_until(lambda: "@@BILAL-PAGES@@" in code(asha), 10))
    check("each sees the other online", wait_until(lambda: "Bilal" in people(asha) and "Asha" in people(bilal), 8),
          (people(asha), people(bilal)))

    # ------------------------------------------------------------------ 4. plain address later
    print("\n== 4. Asha comes back through the plain address (no ?server=, no ?room=)")
    asha.goto(PAGES)
    check("the server is remembered: Asha is Online again", wait_until(lambda: online(asha), 15), conn(asha))
    check("she is back in the same room with both edits, each once",
          wait_until(lambda: parse_qs(urlparse(asha.url).query).get("room", [""])[0] == room
                     and code(asha).count("@@ASHA-PAGES@@") == 1 and code(asha).count("@@BILAL-PAGES@@") == 1, 10),
          asha.url)

    # ------------------------------------------------------------------ 5. the ⚙ Server button
    print("\n== 5. Chen sets the server with the ⚙ Server button instead")
    chen = person()
    chen.goto(PAGES + "?room=" + room)
    wait_until(lambda: home(chen) == "Account on this device", 6)
    chen.once("dialog", lambda d: d.accept(SERVER_WS))
    chen.evaluate("document.getElementById('setServer').click()")
    check("the login page switches to the DRAGON server",
          wait_until(lambda: home(chen) == "Account on the DRAGON server at " + SERVER_HOST, 8), home(chen))
    check("Chen creates an account", sign_up(chen, "Chen"))
    check("Chen is Online in the same room and sees both edits",
          wait_until(lambda: online(chen) and "@@BILAL-PAGES@@" in code(chen) and "@@ASHA-PAGES@@" in code(chen), 15),
          conn(chen))
    link_c = share_link(chen)
    check("Chen's Share link carries the server even though his address did not",
          ("server=" + quote(SERVER_WS, safe="")) in link_c and ("room=" + room) in link_c, link_c)
    check("all three are online together",
          wait_until(lambda: all(n in people(asha) for n in ("Bilal", "Chen")), 8), people(asha))

    # ------------------------------------------------------------------ 6. served by the server
    print("\n== 6. The page served by the DRAGON server itself still shares a clean link")
    dev = person()
    dev.goto(BASE + "/?room=" + room)
    wait_until(lambda: dev.locator("#authScreen").is_visible(), 6)
    check("its login page does not name another site",
          wait_until(lambda: home(dev) == "Account on the DRAGON server", 8), home(dev))
    check("Dev creates an account", sign_up(dev, "Dev"))
    check("Dev is Online with the others", wait_until(lambda: online(dev) and "@@ASHA-PAGES@@" in code(dev), 15))
    check("its Share link has no server= part", share_link(dev) == f"{BASE}/?room={room}")

    errors = [e for pg in pages for e in (pg.evaluate("window.__appErrors || []"))]
    check("no JavaScript errors in any tab", not errors, errors[:3])
    browser.close()

static.shutdown()
shutil.rmtree(site, ignore_errors=True)
passed = sum(1 for _, ok in results if ok)
print(f"\n{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
