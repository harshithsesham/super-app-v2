"""The Chromium driver behind browser tasks: a persistent profile per agent
home (cookies and sign-ins survive between tasks), structural observation
of the page as a list of referenced interactive elements plus a text
digest, and actions addressed by those references.

Playwright's sync API is thread-affine, so a Driver must be created and used
on one thread; the task runner owns that thread.
"""
from __future__ import annotations
import base64, pathlib, re, time
from dataclasses import dataclass, field

SNAPSHOT_JS = r"""
(maxItems) => {
  const sel = 'a[href], button, input, select, textarea, [role="button"], [role="link"], [role="textbox"], [role="checkbox"], [role="radio"], [role="combobox"], [role="menuitem"], [role="tab"], [role="option"], [role="switch"], [contenteditable="true"], summary';
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' && r.bottom > 0 && r.top < innerHeight * 3; };
  const name = (el) => {
    const pick = (v) => (v || '').replace(/\s+/g, ' ').trim();
    return pick(el.getAttribute('aria-label')) || pick(el.getAttribute('placeholder')) || pick(el.alt) || pick(el.title)
      || pick(el.innerText) || pick(el.value) || pick(el.getAttribute('name')) || pick(el.id);
  };
  const role = (el) => {
    const r = el.getAttribute('role'); if (r) return r;
    const t = el.tagName.toLowerCase();
    if (t === 'a') return 'link'; if (t === 'button' || t === 'summary') return 'button';
    if (t === 'select') return 'combobox'; if (t === 'textarea') return 'textbox';
    if (t === 'input') { const ty = (el.type || 'text').toLowerCase();
      if (['button','submit','reset','image'].includes(ty)) return 'button';
      if (ty === 'checkbox' || ty === 'radio') return ty; return 'textbox'; }
    return 'element';
  };
  document.querySelectorAll('[data-muse-ref]').forEach(e => e.removeAttribute('data-muse-ref'));
  const out = []; let i = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (!vis(el)) continue;
    i += 1; const ref = 'e' + i; el.setAttribute('data-muse-ref', ref);
    const r = role(el); let line = `[${ref}] ${r} "${name(el).slice(0, 80)}"`;
    if (r === 'link' && el.href) { try { const u = new URL(el.href); line += ` (${u.pathname.slice(0, 60)}${u.search ? '?' : ''})`; } catch {} }
    if (r === 'textbox' && el.value) line += ` value="${String(el.value).slice(0, 40)}"`;
    if ((r === 'checkbox' || r === 'radio') && el.checked) line += ' [checked]';
    if (el.disabled) line += ' [disabled]';
    out.push(line);
    if (out.length >= maxItems) break;
  }
  const text = (document.body ? document.body.innerText : '').replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n');
  return { items: out, text: text.slice(0, 6000), total: i, scrollY: Math.round(scrollY), scrollH: document.documentElement.scrollHeight, innerH: innerHeight };
}
"""


@dataclass
class Receipt:
    action: str
    dispatch: str = "done"           # done | not_started
    actionability_reason: str = ""
    note: str = ""

    def public(self) -> dict:
        d = {"action": self.action, "dispatch": self.dispatch}
        if self.actionability_reason:
            d["actionability_reason"] = self.actionability_reason
        if self.note:
            d["note"] = self.note
        return d


class Driver:
    def __init__(self, home: pathlib.Path, headless: bool = True):
        from playwright.sync_api import sync_playwright
        self.profile = home / ".browser" / "profile"
        self.profile.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.launch_persistent_context(
            str(self.profile), headless=headless, viewport={"width": 1024, "height": 1100},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
            locale="en-US", args=["--disable-blink-features=AutomationControlled"])
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.set_default_timeout(15000)
        self.snapshot_epoch = 0

    def close(self):
        try:
            self.ctx.close()
        finally:
            self._pw.stop()

    # ------------------------------------------------------------ observe --
    def snapshot(self, max_items: int = 120) -> dict:
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        data = self.page.evaluate(SNAPSHOT_JS, max_items)
        self.snapshot_epoch += 1
        return {"url": self.page.url, "title": self.page.title(), "elements": data["items"],
                "elements_total": data["total"], "text": data["text"],
                "scroll": f"{data['scrollY']}/{max(0, data['scrollH'] - data['innerH'])}", "epoch": self.snapshot_epoch}

    def screenshot_b64(self) -> str:
        try:
            return base64.b64encode(self.page.screenshot(type="jpeg", quality=45, full_page=False)).decode()
        except Exception:  # noqa: BLE001
            return ""

    # -------------------------------------------------------------- act ----
    def _loc(self, ref: str):
        if not re.fullmatch(r"e\d+", ref or ""):
            raise ValueError(f"bad ref {ref!r}; refs look like e12 and come from a snapshot")
        loc = self.page.locator(f'[data-muse-ref="{ref}"]')
        if loc.count() == 0:
            raise LookupError("stale_ref_scope: that reference is not on the current page; take a fresh snapshot")
        return loc.first

    def act(self, a: dict) -> Receipt:
        kind = str(a.get("action", ""))
        r = Receipt(kind)
        try:
            if kind == "navigate":
                url = str(a.get("url", ""))
                if not re.match(r"https?://", url):
                    url = "https://" + url
                self.page.goto(url, wait_until="domcontentloaded")
            elif kind == "click":
                self._loc(str(a.get("ref"))).click(timeout=8000)
                self._settle()
            elif kind == "type":
                loc = self._loc(str(a.get("ref")))
                loc.click(timeout=8000)
                loc.fill(str(a.get("text", "")))
                if a.get("submit"):
                    loc.press("Enter")
                    self._settle()
            elif kind == "press":
                self.page.keyboard.press(str(a.get("key", "Enter")))
                self._settle()
            elif kind == "select":
                self._loc(str(a.get("ref"))).select_option(str(a.get("value", "")))
            elif kind == "scroll":
                if a.get("ref"):
                    self._loc(str(a["ref"])).scroll_into_view_if_needed()
                else:
                    dy = 700 if str(a.get("direction", "down")) == "down" else -700
                    self.page.mouse.wheel(0, dy)
                time.sleep(0.3)
            elif kind == "back":
                self.page.go_back(wait_until="domcontentloaded")
            elif kind == "wait":
                time.sleep(min(float(a.get("seconds", 1)), 10))
            elif kind == "snapshot":
                pass  # observation is appended by the caller
            else:
                r.dispatch, r.actionability_reason = "not_started", f"unknown action {kind!r}"
        except LookupError as e:
            r.dispatch, r.actionability_reason = "not_started", str(e)
        except Exception as e:  # noqa: BLE001
            msg = str(e).splitlines()[0][:200]
            r.dispatch, r.actionability_reason = "not_started", msg
        return r

    def _settle(self):
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=6000)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)
