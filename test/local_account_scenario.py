"""Login and sign-up page without a DRAGON server, tested through the UI in real Chrome.

Two ways people open the editor without the sync server:
  1. double-clicking index.html (a file:// page)
  2. a plain web server, e.g. VS Code Live Server or `python -m http.server`
Both must still show Create account / Log in (name, email, password); the account is then
kept in that browser.

Run (the plain web server part needs one, e.g. `python3 -m http.server 8799` in the project folder):
  python test/local_account_scenario.py [chrome] [plain-server-url]
"""
import sys, os, time, urllib.request
from playwright.sync_api import sync_playwright

CHROME = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None
STATIC = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8799"
FILE_URL = "file://" + os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "index.html"))
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

INIT = "if (window === window.top) { window.__appErrors = []; addEventListener('error', e => window.__appErrors.push(String(e.message))); }"

def run_flow(browser, label, url, shots=None):
    print(f"\n== {label}")
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(INIT)
    pg = ctx.new_page()
    pg.on("dialog", lambda d: d.accept())
    visible = lambda: pg.locator("#authScreen").is_visible()
    err = lambda: pg.locator("#authError").inner_text()
    tab = lambda: pg.locator("#authTabs [aria-selected='true']").inner_text()
    pg.goto(url)
    check(f"[{label}] the page opens on Create account", wait_until(visible, 5) and tab() == "Create account")
    check(f"[{label}] it asks for name, email and password", all(pg.locator(s).is_visible() for s in ["#authName", "#authEmail", "#authPassword"]))
    check(f"[{label}] it says the account is kept on this device", wait_until(lambda: pg.locator("#authHome").inner_text() == "Account on this device", 6)
          and "kept in this browser" in pg.locator("#authNote").inner_text(), pg.locator("#authHome").inner_text())
    if shots: pg.screenshot(path=shots)
    pg.locator("#authName").fill("Suraj Singh")
    pg.locator("#authEmail").fill("suraj@example.com")
    pg.locator("#authPassword").fill("short")
    pg.locator("#authSubmit").click()
    check(f"[{label}] a short password is refused", "at least 8 characters" in err(), err())
    pg.locator("#authPassword").fill("my-secret-pass")
    pg.locator("#authSubmit").click()
    check(f"[{label}] Create account opens the editor", wait_until(lambda: not visible(), 6), err())
    check(f"[{label}] status: this browser only (no server to sync with)", wait_until(lambda: pg.locator("#connBadge").inner_text() == "This browser only", 6), pg.locator("#connBadge").inner_text())
    stored = pg.evaluate("localStorage.getItem('dragonLocalAccounts') || ''")
    check(f"[{label}] the password itself is not stored, only a PBKDF2 hash", "my-secret-pass" not in stored and '"hash"' in stored and '"rounds":310000' in stored, stored[:120])
    pg.locator("#settingsBtn").click()
    check(f"[{label}] Settings shows the account", "suraj@example.com (account on this device)" in pg.locator("#setEmail").inner_text(), pg.locator("#setEmail").inner_text())
    pg.locator("#setThemes .theme-card[data-t='aurora']").click()
    pg.locator("#setName").fill("Suraj")
    pg.locator("#setSave").click()
    wait_until(lambda: pg.locator("#settingsPanel").is_hidden(), 3)
    pg.locator("#code").click(); pg.keyboard.press("Control+End"); pg.keyboard.type("<!-- saved-locally -->")
    time.sleep(0.5)
    pg.reload()
    check(f"[{label}] a reload goes straight to the editor", wait_until(lambda: pg.locator("#code").is_visible(), 6) and not visible())
    check(f"[{label}] name, theme and work are kept", pg.locator("#settingsName").inner_text() == "Suraj" and pg.evaluate("document.documentElement.dataset.theme") == "aurora"
          and wait_until(lambda: "saved-locally" in pg.locator("#code").input_value(), 4))
    pg.locator("#settingsBtn").click()
    pg.locator("#setSignOut").click()
    check(f"[{label}] after logging out it opens on Log in with the email filled in", wait_until(lambda: visible() and tab() == "Log in", 6)
          and pg.locator("#authEmail").input_value() == "suraj@example.com")
    pg.locator("#authPassword").fill("wrong-password")
    pg.locator("#authSubmit").click()
    check(f"[{label}] a wrong password is refused", wait_until(lambda: "Wrong email or password" in err(), 5), err())
    pg.locator("#authTabSignup").click()
    pg.locator("#authName").fill("Copycat")
    pg.locator("#authPassword").fill("another-password")
    pg.locator("#authSubmit").click()
    check(f"[{label}] the same email cannot sign up twice", wait_until(lambda: tab() == "Log in" and "already exists" in err(), 5), err())
    pg.locator("#authPassword").fill("my-secret-pass")
    pg.locator("#authSubmit").click()
    check(f"[{label}] the right password opens the editor with the saved work", wait_until(lambda: not visible(), 6)
          and pg.locator("#settingsName").inner_text() == "Suraj" and "saved-locally" in pg.locator("#code").input_value())
    errors = pg.evaluate("window.__appErrors")
    check(f"[{label}] no JavaScript errors", not errors, errors[:3])
    ctx.close()

with sync_playwright() as p:
    launch = {"args": ["--no-sandbox"]}
    if CHROME: launch["executable_path"] = CHROME
    browser = p.chromium.launch(**launch)
    run_flow(browser, "opened as a file", FILE_URL, shots=os.environ.get("SHOT_FILE"))
    try:
        urllib.request.urlopen(STATIC + "/index.html", timeout=3).read(10)
        static_up = True
    except Exception:
        static_up = False
    if static_up: run_flow(browser, "plain web server", STATIC + "/index.html", shots=os.environ.get("SHOT_STATIC"))
    else: print(f"\n(skipped: no plain web server at {STATIC})")
    browser.close()

passed = sum(1 for _, ok in results if ok)
print(f"\n{passed}/{len(results)} checks passed")
for name, ok in results:
    if not ok: print("FAILED:", name)
sys.exit(0 if passed == len(results) else 1)
