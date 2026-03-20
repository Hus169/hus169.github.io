#!/usr/bin/env python3
"""
FC Evolution Sync — futbin.com/evolutions → index.html
=======================================================
Scrapes active evolutions including:
  - Evolution name
  - Base playstyles (ps)
  - Playstyles+ (plus)
  - Expiry date

Usage:
  python sync_evos.py                                         # dry-run
  python sync_evos.py --apply                                 # write index.html
  python sync_evos.py --html path/to/index.html --apply
  python sync_evos.py --no-scrape futbin_snapshot.json --apply
"""

import argparse, json, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

GREEN="\033[92m"; YELLOW="\033[93m"; RED="\033[91m"; BOLD="\033[1m"; RESET="\033[0m"
def g(s): return f"{GREEN}{s}{RESET}"
def y(s): return f"{YELLOW}{s}{RESET}"
def r(s): return f"{RED}{s}{RESET}"
def b(s): return f"{BOLD}{s}{RESET}"

# Every playstyle key exactly as used in your site's playstyleMap
KNOWN_PLAYSTYLES = [
    "Acrobatic", "Aerial Fortress", "Anticipate", "Block", "Bruiser",
    "Chip Shot", "Cross Claimer", "Dead Ball", "Deflector", "Enforcer",
    "Far Reach", "Far Throw", "Finesse Shot", "First Touch", "Footwork",
    "Gamechanger", "Incisive Pass", "Intercept", "Inventive", "Jockey",
    "Long Ball Pass", "Long Throw", "Low Driven Shot", "Pinged Pass",
    "Power Shot", "Precision Header", "Press Proven", "Quick Step", "Rapid",
    "Relentless", "Rush Out", "Slide Tackle", "Technical", "Tiki Taka",
    "Trickster", "Whipped Pass",
]

# ── Scraper ───────────────────────────────────────────────────────────────────

# ── JS scraper (runs inside the browser on the current page) ─────────────────

SCRAPER_JS = """
(knownPlaystyles) => {
    const results = [];

    function getClass(el) {
        return (el && el.getAttribute && el.getAttribute('class')) || '';
    }

    const cards = document.querySelectorAll('.evolutions-overview-wrapper');

    cards.forEach(card => {
        // ── Name ─────────────────────────────────────────────────
        let name = null;
        const cardTop = card.querySelector('.evolutions-card-top');
        if (cardTop) {
            const badgeWords = ['EVOLUTIONS','NEW','EXPIRED','REWARDS','TRAINING',
                                'BAKERY','PREMIUM','COSMETICS','FS ACADEMY'];
            for (const el of cardTop.querySelectorAll('*')) {
                const c = getClass(el).toLowerCase();
                if (c.includes('badge') || c.includes('og-pill') || c.includes('pill')) continue;
                const txt = (el.childNodes[0]?.textContent || el.textContent || '').trim();
                if (txt.length > 3 && txt.length < 80 && !/^[A-Z0-9\\s+]+$/.test(txt)) {
                    if (!badgeWords.some(bw => txt.toUpperCase() === bw)) {
                        name = txt; break;
                    }
                }
            }
            if (!name) {
                let raw = (cardTop.textContent || '').trim();
                badgeWords.forEach(bw => {
                    raw = raw.replace(new RegExp('\\b' + bw + '\\b', 'gi'), '');
                });
                raw = raw.replace(/\\s+/g, ' ').trim();
                if (raw.length > 3) name = raw;
            }
        }
        if (!name) return;

        // ── Expiry ────────────────────────────────────────────────
        let expiresText = null;
        let expiresTextFallback = null;
        card.querySelectorAll('.evolution-upgrade').forEach(block => {
            const labelEl = block.querySelector('.xxs-font, [class*="text-faded"], .unlock-within');
            const valueEl = block.querySelector('.xs-font, [class*="semi-bold"]');
            if (!labelEl || !valueEl) return;
            const labelText = (labelEl.textContent || '').trim().toUpperCase();
            if (labelText.includes('UNLOCK')) {
                // UNLOCK = real player deadline (when you can no longer complete the evo)
                expiresText = (valueEl.textContent || '').trim();
            } else if (labelText.includes('EXPIRE')) {
                // EXPIRES = when the card disappears — fallback only
                expiresTextFallback = (valueEl.textContent || '').trim();
            }
        });
        expiresText = expiresText || expiresTextFallback;
        if (!expiresText) {
            const m = (card.textContent || '').match(
                /UNLOCK(?:\\s+WITHIN)?\\s*(\\d+)\\s*(day|days|week|weeks|hour|hours)/i
            );
            if (m) expiresText = m[1] + ' ' + m[2];
        }

        // ── Playstyles ────────────────────────────────────────────
        const psBase = [], psPlus = [];
        card.querySelectorAll('.xs-row, .border-bottom').forEach(row => {
            const labelEl = row.querySelector('.text-faded');
            const valueEl = row.querySelector('.positive-color');
            if (!labelEl || !valueEl) return;
            const label = (labelEl.textContent || '').trim();
            if (label !== 'PS' && label !== 'PS+') return;
            let psName = '';
            for (const node of valueEl.childNodes) {
                if (node.nodeType === Node.TEXT_NODE) psName += node.textContent;
            }
            psName = psName.trim();
            const matched = knownPlaystyles.find(ps => ps.toLowerCase() === psName.toLowerCase());
            if (!matched) return;
            if (label === 'PS+') {
                if (!psPlus.includes(matched)) psPlus.push(matched);
            } else {
                if (!psBase.includes(matched)) psBase.push(matched);
            }
        });
        const plusSet = new Set(psPlus);
        const psBaseFiltered = psBase.filter(ps => !plusSet.has(ps));

        // ── Position, Max Rating & OVR Boost ──────────────────────
        // Scoped strictly to .evo-box-req (Player Requirements section)
        let position = null;
        let maxRating = null;
        const reqBox = card.querySelector('.evo-box-req');
        if (reqBox) {
            reqBox.querySelectorAll('.xxs-row').forEach(row => {
                const labelEl = row.querySelector('.text-faded');
                const valueEl = row.querySelector('.positive-color');
                if (!labelEl || !valueEl) return;
                const label = (labelEl.textContent || '').trim().toUpperCase();
                const value = (valueEl.textContent || '').trim();
                if (label === 'POSITION') position = value;
                if (label === 'OVERALL') {
                    const m = value.match(/\\d+/);
                    if (m) maxRating = parseInt(m[0]);
                }
            });
        }

        // ── OVR Boost (+40) and OVR Cap (91) ─────────────────────
        // From: <div class="positive-color">+40<span class="evo-cap-line"><span class="evo-cap-arrow"> | </span><span>91</span></span></div>
        let ovrBoost = null;
        let ovrCap   = null;
        card.querySelectorAll('.border-bottom.xs-row').forEach(row => {
            const labelEl = row.querySelector('.text-faded');
            const valueEl = row.querySelector('.positive-color');
            if (!labelEl || !valueEl) return;
            if ((labelEl.textContent || '').trim().toLowerCase() !== 'overall') return;
            // Boost = leading text node before the cap span
            let boost = '';
            for (const node of valueEl.childNodes) {
                if (node.nodeType === Node.TEXT_NODE) boost += node.textContent;
            }
            boost = boost.trim();
            if (boost) ovrBoost = boost;
            // Cap = last <span> inside .evo-cap-line
            const capLine = valueEl.querySelector('.evo-cap-line');
            if (capLine) {
                const spans = capLine.querySelectorAll('span');
                const last = spans[spans.length - 1];
                if (last) {
                    const capNum = parseInt((last.textContent || '').trim());
                    if (!isNaN(capNum)) ovrCap = capNum;
                }
            }
        });

        results.push({
            name: name.trim(),
            expiresText: expiresText || null,
            ps: psBaseFiltered,
            plus: psPlus,
            position: position,
            maxRating: maxRating,
            ovrBoost: ovrBoost,
            ovrCap:   ovrCap,
        });
    });

    return results;
}
"""


def _load_page(page, url, label):
    """Navigate to url, wait for evo cards, scroll to load lazy content."""
    print(f"  → {label}: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    try:
        page.wait_for_selector(".evolutions-overview-wrapper", timeout=20_000)
    except Exception:
        print(y("    Selector timeout — trying extended wait..."))
        page.wait_for_timeout(15_000)
    for _ in range(8):
        page.mouse.wheel(0, 800)
        page.wait_for_timeout(400)
    page.wait_for_timeout(2000)
    count = page.locator(".evolutions-overview-wrapper").count()
    print(f"    Found {count} card(s)")
    return count


def _parse_raw(raw_items, expired_flag=False):
    """Convert browser-returned items to normalised dicts."""
    today = datetime.now(timezone.utc).date()
    output = []
    for item in raw_items:
        days = parse_days(item.get("expiresText") or "")
        if days is None:
            expires_iso = None
        elif days < 1.0:
            # Sub-day precision: store as full ISO datetime so frontend can show hours
            from datetime import datetime as _dt
            expires_dt = _dt.now(timezone.utc) + timedelta(days=days)
            expires_iso = expires_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            expires_iso = (today + timedelta(days=int(days))).isoformat()
        entry = {
            "name":      normalise_name(item["name"]),
            "ps":        item.get("ps", []),
            "plus":      item.get("plus", []),
            "days_left": days,
            "expires":   expires_iso,
            "exp":       expired_flag,
            "pos":       item.get("position"),
            "maxRating": item.get("maxRating"),
            "ovrBoost": item.get("ovrBoost"),
            "ovrCap":   item.get("ovrCap"),
        }
        status = r("expired") if expired_flag else (f"expires {expires_iso}" if expires_iso else y("no expiry"))
        ps_str   = ", ".join(entry["ps"])   or "—"
        plus_str = ", ".join(entry["plus"]) or "—"
        print(f"  {g('✓')} {entry['name']:<40} | ps: {ps_str:<25} | ps+: {plus_str:<20} | {status}")
        output.append(entry)
    return output


def scrape_futbin() -> tuple[list[dict], list[dict]]:
    """Scrape active + expired evolutions. Returns (active, expired)."""
    from playwright.sync_api import sync_playwright

    print(f"\n{b('Launching browser')}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1280,900",
            ],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-GB",
            timezone_id="Europe/London",
            java_script_enabled=True,
            extra_http_headers={
                "Accept-Language": "en-GB,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            },
        )
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-GB', 'en'] });
            window.chrome = { runtime: {} };
        """)

        page = ctx.new_page()
        known_ps = KNOWN_PLAYSTYLES

        # ── Active evolutions ─────────────────────────────────────
        print(f"\n{b('Active evolutions')}")
        _load_page(page, "https://www.futbin.com/evolutions", "active")
        raw_active = page.evaluate(SCRAPER_JS, known_ps)

        # ── Expired evolutions ────────────────────────────────────
        print(f"\n{b('Expired evolutions')}")
        _load_page(page, "https://www.futbin.com/evolutions/expired", "expired")
        raw_expired = page.evaluate(SCRAPER_JS, known_ps)

        browser.close()

    print(f"\n{b('Parsing active...')}")
    active  = _parse_raw(raw_active,  expired_flag=False)
    print(f"\n{b('Parsing expired...')}")
    expired = _parse_raw(raw_expired, expired_flag=True)

    # Deduplicate each list by name
    def dedup(lst):
        seen, out = set(), []
        for e in lst:
            k = e["name"].lower()
            if k not in seen:
                seen.add(k); out.append(e)
        return out

    active  = dedup(active)
    expired = dedup(expired)

    print(f"\n  Scraped {b(str(len(active)))} active + {b(str(len(expired)))} expired evolutions.\n")
    return active, expired




def parse_days(text: str) -> float | None:
    """Return days as a float so sub-day hours are preserved (e.g. 21h → 0.875)."""
    if not text: return None
    text = text.lower().strip()
    m = re.search(r'(\d+)\s*month', text)
    if m: return int(m.group(1)) * 30
    m = re.search(r'(\d+)\s*week', text)
    if m:
        days = int(m.group(1)) * 7
        d = re.search(r'(\d+)\s*day', text)
        if d: days += int(d.group(1))
        return float(days)
    m = re.search(r'(\d+)\s*day', text)
    if m:
        days = int(m.group(1))
        h = re.search(r'(\d+)\s*hour', text)
        return float(days) + (int(h.group(1)) / 24.0 if h else 0.0)
    m = re.search(r'(\d+)\s*hour', text)
    if m: return int(m.group(1)) / 24.0
    return None


def normalise_name(name: str) -> str:
    name = re.sub(r'\s+', ' ', name).strip()
    return name.replace('\u2019', "'").replace('\u2018', "'")


# ── index.html parser ─────────────────────────────────────────────────────────

RAW_DATA_RE = re.compile(r'(const\s+rawData\s*=\s*\[)(.*?)(\];)', re.DOTALL)


def load_html(path): return path.read_text(encoding="utf-8")


def extract_raw_data(html):
    m = RAW_DATA_RE.search(html)
    if not m: raise ValueError("Could not find 'const rawData = [...]' in index.html")
    block = m.group(2)
    rows, depth, start = [], 0, None
    for i, ch in enumerate(block):
        if ch == '{':
            if depth == 0: start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                parsed = parse_js_obj(block[start:i+1])
                if parsed: rows.append(parsed)
                start = None
    return rows


def parse_js_obj(s):
    # Quote unquoted JS keys so json.loads can handle it
    try:
        s2 = re.sub(r'(?<=[{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r' "\1":', s)
        s2 = re.sub(r'\btrue\b', 'true', s2)
        s2 = re.sub(r'\bfalse\b', 'false', s2)
        s2 = re.sub(r',\s*([}\]])', r'\1', s2)
        return json.loads(s2)
    except Exception:
        pass
    # Regex fallback - handles both quoted and unquoted keys
    result = {}
    for f, p in [
        ('name',    r'(?:[\"\'])?name(?:[\"\'])?\s*:\s*"([^"]*)"'),
        ('expires', r'(?:[\"\'])?expires(?:[\"\'])?\s*:\s*"([^"]*)"'),
    ]:
        mm = re.search(p, s)
        if mm: result[f] = mm.group(1)
    mm = re.search(r'\bexp\b\s*:\s*(true|false)', s)
    if mm: result['exp'] = mm.group(1) == 'true'
    for f, p in [
        ('ps',   r'(?:[\"\'])?ps(?:[\"\'])?\s*:\s*\[([^\]]*)\]'),
        ('plus', r'(?:[\"\'])?plus(?:[\"\'])?\s*:\s*\[([^\]]*)\]'),
    ]:
        mm = re.search(p, s)
        if mm: result[f] = re.findall(r'"([^"]*)"', mm.group(1))
        else: result.setdefault(f, [])
    return result if 'name' in result else None


# ── Diff & patch ──────────────────────────────────────────────────────────────

def compute_diff(existing, futbin_active, futbin_expired):
    active_map  = {e['name'].lower(): e for e in futbin_active}
    expired_map = {e['name'].lower(): e for e in futbin_expired}
    ex_map      = {e.get('name','').lower(): e for e in existing}
    new_evos, new_expired, expired_now, updated = [], [], [], []

    # New active evos not yet in index.html
    for key, data in active_map.items():
        if key not in ex_map:
            new_evos.append(data)
        else:
            ex = ex_map[key]
            changed = {}
            if data.get('expires') and ex.get('expires') != data['expires']:
                changed['expires'] = data['expires']
            if data.get('ps') and not ex.get('ps'):
                changed['ps'] = data['ps']
            if data.get('plus') and not ex.get('plus'):
                changed['plus'] = data['plus']
            if data.get('pos') and not ex.get('pos'):
                changed['pos'] = data['pos']
            if data.get('maxRating') and not ex.get('maxRating'):
                changed['maxRating'] = data['maxRating']
            if data.get('ovrBoost') and not ex.get('ovrBoost'):
                changed['ovrBoost'] = data['ovrBoost']
            if data.get('ovrCap') and not ex.get('ovrCap'):
                changed['ovrCap'] = data['ovrCap']
            if changed:
                updated.append({**ex, **changed})

    # New expired evos not yet in index.html
    for key, data in expired_map.items():
        if key not in ex_map:
            new_expired.append(data)

    # Evos in index.html that are now on the expired page → mark exp: true
    # BUT only if they are NOT also still on the active page (active takes priority)
    for key, ex_data in ex_map.items():
        if not ex_data.get('exp', False) and key in expired_map and key not in active_map:
            expired_now.append(ex_data)

    return {
        'new_evos':    new_evos,
        'new_expired': new_expired,
        'expired_now': expired_now,
        'updated':     updated,
    }


def js_array(lst):
    """Format a Python list as a JS array string."""
    items = ', '.join(f'"{v}"' for v in lst)
    return f'[{items}]'


def patch_html(html, diff):
    m = RAW_DATA_RE.search(html)
    if not m: raise ValueError("rawData block not found")
    block = m.group(2)

    # 0. Auto-expire any entry whose expires date is now in the past
    today = datetime.now(timezone.utc).date().isoformat()
    def flip_if_past(mo):
        obj = mo.group(0)
        # Only touch entries that are still exp: false
        if 'exp: true' in obj or 'exp:true' in obj:
            return obj
        expires_m = re.search(r'"expires"\s*:\s*"([^"]+)"', obj)
        if expires_m and expires_m.group(1) < today:
            obj = re.sub(r'\bexp\s*:\s*false', 'exp: true', obj)
        return obj
    block = re.sub(r'\{[^{}]+\}', flip_if_past, block)

    # 1. Mark expired (disappeared from futbin)
    for evo in diff['expired_now']:
        name = re.escape(evo['name'].replace('"', '\\"'))
        block = re.sub(
            rf'(\{{[^{{}}]*?"name"\s*:\s*"{name}"[^{{}}]*?)\bexp\s*:\s*false',
            r'\1exp: true', block)

    # 2. Update expiry / ps / plus on existing evos
    for evo in diff['updated']:
        name_esc = re.escape(evo['name'].replace('"', '\\"'))
        def replacer(mo, evo=evo):
            obj = mo.group(0)
            if 'expires' in evo:
                if '"expires"' in obj:
                    obj = re.sub(r'"expires"\s*:\s*"[^"]*"', f'"expires": "{evo["expires"]}"', obj)
                else:
                    obj = obj.rstrip('}').rstrip() + f', "expires": "{evo["expires"]}"' + '}'
            if 'ps' in evo:
                obj = re.sub(r'\bps\s*:\s*\[[^\]]*\]', f'ps: {js_array(evo["ps"])}', obj)
            if 'plus' in evo:
                obj = re.sub(r'\bplus\s*:\s*\[[^\]]*\]', f'plus: {js_array(evo["plus"])}', obj)
            if 'pos' in evo:
                if 'pos:' in obj:
                    obj = re.sub(r'pos\s*:\s*"[^"]*"', f'pos: "{evo["pos"]}"', obj)
                else:
                    obj = obj.rstrip('}').rstrip() + f', pos: "{evo["pos"]}"' + '}'
            if 'maxRating' in evo:
                if 'maxRating:' in obj:
                    obj = re.sub(r'maxRating\s*:\s*\d+', f'maxRating: {evo["maxRating"]}', obj)
                else:
                    obj = obj.rstrip('}').rstrip() + f', maxRating: {evo["maxRating"]}' + '}'
            if 'ovrBoost' in evo:
                boost_val = f'"{evo["ovrBoost"]}"'
                if 'ovrBoost:' in obj:
                    obj = re.sub(r'ovrBoost\s*:\s*"[^"]*"', f'ovrBoost: {boost_val}', obj)
                else:
                    obj = obj.rstrip('}').rstrip() + f', ovrBoost: {boost_val}' + '}'
            if 'ovrCap' in evo and evo['ovrCap']:
                cap_val = str(evo['ovrCap'])
                if 'ovrCap:' in obj:
                    obj = re.sub(r'ovrCap\s*:\s*\d+', f'ovrCap: {cap_val}', obj)
                else:
                    obj = obj.rstrip('}').rstrip() + f', ovrCap: {cap_val}' + '}'
            return obj
        block = re.sub(rf'\{{[^{{}}]*?"name"\s*:\s*"{name_esc}"[^{{}}]*?\}}', replacer, block)

    # 3. Prepend new active evos
    new_lines = []
    for evo in diff['new_evos']:
        exp_field  = f', "expires": "{evo["expires"]}"' if evo.get('expires') else ''
        ps_field   = js_array(evo.get('ps', []))
        plus_field = js_array(evo.get('plus', []))
        pos_field       = f', pos: "{evo["pos"]}"'           if evo.get("pos")       else ''
        rating_field    = f', maxRating: {evo["maxRating"]}'   if evo.get("maxRating") else ''
        boost_field     = f', ovrBoost: "{evo["ovrBoost"]}"' if evo.get("ovrBoost") else ''
        cap_field       = f', ovrCap: {evo["ovrCap"]}'          if evo.get("ovrCap")   else ''
        new_lines.append(
            f'\n        {{ name: "{evo["name"]}", ps: {ps_field}, plus: {plus_field}, exp: false{exp_field}{pos_field}{rating_field}{boost_field}{cap_field} }},  // AUTO-ADDED'
        )

    # 4. Append new expired evos (scraped from /evolutions/expired, not seen before)
    expired_lines = []
    for evo in diff.get('new_expired', []):
        exp_field  = f', "expires": "{evo["expires"]}"' if evo.get('expires') else ''
        ps_field   = js_array(evo.get('ps', []))
        plus_field = js_array(evo.get('plus', []))
        pos_field_e    = f', pos: "{evo["pos"]}"'           if evo.get("pos")       else ''
        rating_field_e = f', maxRating: {evo["maxRating"]}'   if evo.get("maxRating") else ''
        boost_field_e  = f', ovrBoost: "{evo["ovrBoost"]}"' if evo.get("ovrBoost") else ''
        cap_field_e    = f', ovrCap: {evo["ovrCap"]}'          if evo.get("ovrCap")   else ''
        expired_lines.append(
            f'\n        {{ name: "{evo["name"]}", ps: {ps_field}, plus: {plus_field}, exp: true{exp_field}{pos_field_e}{rating_field_e}{boost_field_e}{cap_field_e} }},  // AUTO-ADDED (expired)'
        )

    if new_lines or expired_lines:
        # Strip any existing AUTO-ADDED header at the top of the block to avoid duplicates
        block = re.sub(r'^\s*// ── AUTO-ADDED by sync_evos\.py ──\s*', '', block)
        block = '\n        // ── AUTO-ADDED by sync_evos.py ──' + ''.join(new_lines) + ''.join(expired_lines) + block

    # Ensure ]; lands on its own line — if block ends in a comment the ]; would
    # otherwise be appended to it, making it invisible to the JS parser.
    block = block.rstrip('\n') + '\n    '
    return html[:m.start()] + m.group(1) + block + m.group(3) + html[m.end():]


def inject_expiry_display(html):
    """Idempotent: add expiry badge CSS + JS helpers to index.html."""
    if 'function msUntil(' in html:
        return html

    OLD_TAG = "const tag = evo.exp ? '<span class=\"status-tag\">Expired</span>' : '';"
    NEW_TAG = (
        'const tag = evo.exp\n'
        '                ? \'<span class="status-tag">Expired</span>\'\n'
        '                : evo.expires\n'
        '                    ? buildExpiryTag(evo.expires)\n'
        '                    : \'\';'
    )
    HELPER = '''    function msUntil(isoDate) {
        if (!isoDate) return NaN;
        const target = /T\\d/.test(isoDate)
            ? new Date(isoDate)
            : new Date(isoDate + 'T23:59:59Z');
        const ms = target - Date.now();
        return isNaN(ms) ? NaN : ms;
    }
    function daysUntil(isoDate) {
        return Math.ceil(msUntil(isoDate) / (1000 * 60 * 60 * 24));
    }
    function buildExpiryTag(isoDate) {
        const ms = msUntil(isoDate);
        if (isNaN(ms) || ms < 0) return '<span class="status-tag">Expired</span>';
        if (ms < 1000 * 60 * 60 * 24) {
            const totalMins = Math.ceil(ms / 60000);
            const hours = Math.floor(totalMins / 60);
            const mins  = totalMins % 60;
            if (hours === 0) return `<span class="expiry-tag expiry-urgent">⏳ ${mins}m left</span>`;
            if (hours <= 2)  return `<span class="expiry-tag expiry-urgent">⏳ ${hours}h ${mins}m left</span>`;
            return `<span class="expiry-tag expiry-urgent">⏳ ${hours}h left</span>`;
        }
        const days = Math.ceil(ms / (1000 * 60 * 60 * 24));
        if (days <= 2) return `<span class="expiry-tag expiry-urgent">⏳ ${days}d left</span>`;
        return `<span class="expiry-tag">⏳ ${days}d left</span>`;
    }
    function render() {'''

    OLD_CSS = '.status-tag { font-size: 0.65rem; padding: 2px 8px; border-radius: 4px; background: #333; color: #888; margin-left: 10px; font-weight: normal; }'
    NEW_CSS = (OLD_CSS +
        '\n        .expiry-tag { font-size: 0.65rem; padding: 2px 8px; border-radius: 4px; '
        'background: #0f2e1e; color: #00cc88; margin-left: 10px; font-weight: normal; border: 1px solid #00cc8840; }'
        '\n        .expiry-urgent { background: #2e1a0f !important; color: #ff8c42 !important; border-color: #ff8c4240 !important; }')

    if OLD_TAG in html:       html = html.replace(OLD_TAG, NEW_TAG)
    if '    function render() {' in html: html = html.replace('    function render() {', HELPER)
    if OLD_CSS in html:       html = html.replace(OLD_CSS, NEW_CSS)
    return html


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Write changes to index.html')
    parser.add_argument('--html', default='index.html', help='Path to index.html')
    parser.add_argument('--no-scrape', metavar='JSON', help='Use saved futbin_snapshot.json')
    args = parser.parse_args()

    html_path = Path(args.html)
    if not html_path.exists():
        print(r(f'✗ Not found: {html_path}')); sys.exit(1)

    if args.no_scrape:
        snapshot = json.loads(Path(args.no_scrape).read_text())
        # Support both old format (flat list) and new format (dict with active/expired)
        if isinstance(snapshot, dict):
            futbin_active  = snapshot.get('active', [])
            futbin_expired = snapshot.get('expired', [])
        else:
            futbin_active  = snapshot
            futbin_expired = []
        print(f"Loaded {len(futbin_active)} active + {len(futbin_expired)} expired evos from {args.no_scrape}")
    else:
        futbin_active, futbin_expired = scrape_futbin()

    if not futbin_active and not futbin_expired:
        print(r('No evolutions scraped.')); sys.exit(1)

    Path('futbin_snapshot.json').write_text(
        json.dumps({'active': futbin_active, 'expired': futbin_expired}, indent=2)
    )

    html = load_html(html_path)
    existing_evos = extract_raw_data(html)
    print(f"  {b(str(len(existing_evos)))} evolutions in your current index.html")

    diff = compute_diff(existing_evos, futbin_active, futbin_expired)

    print(f"\n{'━'*60}\n  {b('SYNC REPORT')}\n{'━'*60}")

    if diff['new_evos']:
        print(f"\n  {g('NEW ACTIVE')} ({len(diff['new_evos'])}):")
        for e in diff['new_evos']:
            ps_str   = ', '.join(e['ps'])   or '(none scraped — add manually)'
            plus_str = ', '.join(e['plus']) or '(none scraped — add manually)'
            exp_str  = e.get('expires') or 'no expiry'
            print(f"    {g('+')} {e['name']}")
            print(f"         ps:      {ps_str}")
            print(f"         ps+:     {plus_str}")
            print(f"         expires: {exp_str}")
    else:
        print(f"\n  {g('✓')} No new active evolutions.")

    if diff['new_expired']:
        print(f"\n  {r('NEW EXPIRED')} ({len(diff['new_expired'])}):")
        for e in diff['new_expired']: print(f"    {r('+')} {e['name']} (added as expired)")
    else:
        print(f"\n  {g('✓')} No new expired evolutions.")

    if diff['expired_now']:
        print(f"\n  {r('NOW EXPIRED')} ({len(diff['expired_now'])}):")
        for e in diff['expired_now']: print(f"    {r('✗')} {e['name']}")
    else:
        print(f"\n  {g('✓')} No newly-expired evolutions.")

    if diff['updated']:
        print(f"\n  {y('UPDATED')} ({len(diff['updated'])}):")
        for e in diff['updated']:
            parts = []
            if 'expires' in e: parts.append(f"expires → {e['expires']}")
            if 'ps'      in e: parts.append(f"ps → {e['ps']}")
            if 'plus'    in e: parts.append(f"plus → {e['plus']}")
            print(f"    {y('~')} {e['name']}: {', '.join(parts)}")

    if not any(diff.values()):
        print(f"\n  {g('✅ Already up to date!')}"); return

    print(f"\n{'━'*60}")

    if args.apply:
        updated_html = patch_html(html, diff)
        updated_html = inject_expiry_display(updated_html)
        html_path.write_text(updated_html, encoding='utf-8')
        print(f"\n  {g('✅ index.html updated!')} → {html_path}")
        print(f"  Commit & push to GitHub to go live.\n")

        # Warn about any new evos where ps/plus couldn't be scraped
        manual = [e for e in diff['new_evos'] if not e.get('ps') and not e.get('plus')]
        if manual:
            print(f"  {y('⚠ Playstyles not found for these new evos — fill in manually:')}")
            for e in manual:
                print(f"    · {e['name']}")
            print()
    else:
        print(f"\n  {y('DRY RUN')} — no files written.")
        print(f"  Run with {b('--apply')} to write changes.\n")


if __name__ == '__main__':
    main()
