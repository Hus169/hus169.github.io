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
# Termux/ARM-compatible scraper using cloudscraper + BeautifulSoup.
# Install deps: pip install cloudscraper beautifulsoup4

BADGE_WORDS = {'EVOLUTIONS','NEW','EXPIRED','REWARDS','TRAINING',
               'BAKERY','PREMIUM','COSMETICS','FS ACADEMY'}

def _parse_card_bs4(card, known_ps):
    """Parse one BeautifulSoup .evolutions-overview-wrapper tag → raw dict."""
    # ── Name ──────────────────────────────────────────────────────
    name = None
    card_top = card.select_one('.evolutions-card-top')
    if card_top:
        for el in card_top.find_all(True):
            cls = ' '.join(el.get('class') or []).lower()
            if any(x in cls for x in ('badge', 'og-pill', 'pill')):
                continue
            txt = (el.get_text(strip=True) or '')
            if 3 < len(txt) < 80 and not re.match(r'^[A-Z0-9\s+]+$', txt):
                if txt.upper() not in BADGE_WORDS:
                    name = txt; break
        if not name:
            raw = card_top.get_text(' ', strip=True)
            for bw in BADGE_WORDS:
                raw = re.sub(rf'\b{bw}\b', '', raw, flags=re.I)
            raw = raw.strip()
            if len(raw) > 3:
                name = raw
    if not name:
        return None

    # ── Expiry ────────────────────────────────────────────────────
    expires_text = None
    expires_fallback = None
    for block in card.select('.evolution-upgrade'):
        label_el = block.select_one('.xxs-font, .unlock-within') or \
                   next((e for e in block.find_all(True)
                         if 'text-faded' in (e.get('class') or [])), None)
        value_el = block.select_one('.xs-font') or \
                   next((e for e in block.find_all(True)
                         if 'semi-bold' in ' '.join(e.get('class') or [])), None)
        if not label_el or not value_el:
            continue
        lbl = label_el.get_text(strip=True).upper()
        val = value_el.get_text(strip=True)
        if 'UNLOCK' in lbl:
            expires_text = val
        elif 'EXPIR' in lbl:
            expires_fallback = val
    expires_text = expires_text or expires_fallback
    if not expires_text:
        m = re.search(
            r'UNLOCK(?:\s+WITHIN)?\s*(\d+)\s*(day|days|week|weeks|hour|hours)',
            card.get_text(), re.I)
        if m:
            expires_text = m.group(1) + ' ' + m.group(2)

    # ── Playstyles ────────────────────────────────────────────────
    from bs4 import NavigableString as _NS
    ps_base, ps_plus = [], []
    ps_base_caps, ps_plus_caps = [], []   # slot-limit per playstyle (the "|7" number)
    for row in card.select('.xs-row, .border-bottom'):
        label_el = next((e for e in row.find_all(True)
                         if 'text-faded' in (e.get('class') or [])), None)
        value_el = next((e for e in row.find_all(True)
                         if 'positive-color' in (e.get('class') or [])), None)
        if not label_el or not value_el:
            continue
        lbl = label_el.get_text(strip=True)
        if lbl not in ('PS', 'PS+'):
            continue
        # Direct text children only — skip the evo-cap-line span
        ps_name = ''.join(
            str(n) for n in value_el.children if isinstance(n, _NS)
        ).strip()
        matched = next((p for p in known_ps
                        if p.lower() == ps_name.lower()), None)
        if not matched:
            continue
        # Cap number lives in the last <span> inside .evo-cap-line
        cap = None
        cap_line = value_el.select_one('.evo-cap-line')
        if cap_line:
            spans = cap_line.find_all('span')
            if spans:
                try: cap = int(spans[-1].get_text(strip=True))
                except ValueError: pass
        if lbl == 'PS+':
            if matched not in ps_plus:
                ps_plus.append(matched)
                ps_plus_caps.append(cap)
        else:
            if matched not in ps_base:
                ps_base.append(matched)
                ps_base_caps.append(cap)
    plus_set = set(ps_plus)
    # Filter base list, keeping caps in sync
    filtered = [(p, c) for p, c in zip(ps_base, ps_base_caps) if p not in plus_set]
    ps_base      = [p for p, _ in filtered]
    ps_base_caps = [c for _, c in filtered]

    # ── Position & Max Rating (from .evo-box-req) ─────────────────
    position = max_rating = None
    req_box = card.select_one('.evo-box-req')
    if req_box:
        for row in req_box.select('.xxs-row'):
            label_el = next((e for e in row.find_all(True)
                             if 'text-faded' in (e.get('class') or [])), None)
            value_el = next((e for e in row.find_all(True)
                             if 'positive-color' in (e.get('class') or [])), None)
            if not label_el or not value_el:
                continue
            lbl = label_el.get_text(strip=True).upper()
            val = value_el.get_text(strip=True)
            if lbl == 'POSITION':
                position = val
            elif lbl == 'OVERALL':
                m = re.search(r'\d+', val)
                if m: max_rating = int(m.group())

    # ── OVR Boost & Cap ───────────────────────────────────────────
    ovr_boost = ovr_cap = None
    for row in card.select('.border-bottom.xs-row'):
        label_el = next((e for e in row.find_all(True)
                         if 'text-faded' in (e.get('class') or [])), None)
        value_el = next((e for e in row.find_all(True)
                         if 'positive-color' in (e.get('class') or [])), None)
        if not label_el or not value_el:
            continue
        if label_el.get_text(strip=True).lower() != 'overall':
            continue
        from bs4 import NavigableString as _NS
        boost = ''.join(
            str(n) for n in value_el.children
            if isinstance(n, _NS)
        ).strip()
        if boost:
            ovr_boost = boost
        cap_line = value_el.select_one('.evo-cap-line')
        if cap_line:
            spans = cap_line.find_all('span')
            if spans:
                cap_num = spans[-1].get_text(strip=True)
                try: ovr_cap = int(cap_num)
                except ValueError: pass

    return {
        'name':        name.strip(),
        'expiresText': expires_text,
        'ps':          ps_base,
        'psCaps':      ps_base_caps,
        'plus':        ps_plus,
        'plusCaps':    ps_plus_caps,
        'position':    position,
        'maxRating':   max_rating,
        'ovrBoost':    ovr_boost,
        'ovrCap':      ovr_cap,
    }


def _fetch_evos_bs4(session, url, label):
    """Fetch one futbin evolutions page, return list of raw dicts."""
    from bs4 import BeautifulSoup
    print(f"  → {label}: {url}")
    resp = session.get(url, timeout=40)
    soup = BeautifulSoup(resp.text, 'html.parser')
    cards = soup.select('.evolutions-overview-wrapper')
    print(f"    Found {len(cards)} card(s)")
    if not cards:
        print(y("    No cards found in static HTML — futbin may be rendering via JS."))
        print(y("    See 'Manual snapshot fallback' in the README or run with --no-scrape."))
    results = []
    for card in cards:
        item = _parse_card_bs4(card, KNOWN_PLAYSTYLES)
        if item:
            results.append(item)
    return results


def scrape_futbin() -> tuple[list[dict], list[dict]]:
    """Scrape active + expired evolutions. Returns (active, expired).
    Uses curl_cffi to impersonate Chrome TLS fingerprint (bypasses Cloudflare).
    Falls back to cloudscraper if curl_cffi is unavailable.
    """
    try:
        from curl_cffi import requests as cffi_requests
        session = cffi_requests.Session(impersonate="chrome124")
        print(f"\n{b('Fetching pages (curl_cffi / Chrome TLS)')}")
    except ImportError:
        try:
            import cloudscraper
            session = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
            )
            print(f"\n{b('Fetching pages (cloudscraper fallback)')}")
            print(y("  Tip: install curl_cffi for better Cloudflare bypass:"))
            print(y("       pip install curl_cffi"))
        except ImportError:
            print(r("No HTTP scraping library found. Run:"))
            print(r("  pip install curl_cffi beautifulsoup4"))
            sys.exit(1)

    try:
        from bs4 import BeautifulSoup  # noqa: F401 — verify import
    except ImportError:
        print(r("beautifulsoup4 not installed. Run:"))
        print(r("  pip install beautifulsoup4"))
        sys.exit(1)

    print(f"\n{b('Active evolutions')}")
    raw_active  = _fetch_evos_bs4(session, "https://www.futbin.com/evolutions",         "active")

    print(f"\n{b('Expired evolutions')}")
    raw_expired = _fetch_evos_bs4(session, "https://www.futbin.com/evolutions/expired",  "expired")

    print(f"\n{b('Parsing active...')}")
    active  = _parse_raw(raw_active,  expired_flag=False)
    print(f"\n{b('Parsing expired...')}")
    expired = _parse_raw(raw_expired, expired_flag=True)

    def dedup(lst):
        seen, out = set(), []
        for e in lst:
            k = e['name'].lower()
            if k not in seen:
                seen.add(k); out.append(e)
        return out

    active  = dedup(active)
    expired = dedup(expired)

    if not active and not expired:
        print(y("\n  ⚠ Zero cards parsed from HTML."))
        print(y("  Futbin likely renders cards client-side (React SPA)."))
        print(y("  ─── Manual snapshot fallback ────────────────────────────────"))
        print(y("  1. Open https://www.futbin.com/evolutions in a desktop browser"))
        print(y("  2. Open DevTools → Console (F12)"))
        print(y("  3. Paste the SCRAPER_JS from the original sync_evos.py"))
        print(y("     and run: copy(JSON.stringify(results))"))
        print(y("  4. Save as futbin_snapshot.json with format:"))
        print(y('     {"active": [...], "expired": [...]}'))
        print(y("  5. Run: python sync_evos.py --no-scrape futbin_snapshot.json --apply"))
        print(y("  ────────────────────────────────────────────────────────────"))

    print(f"\n  Scraped {b(str(len(active)))} active + {b(str(len(expired)))} expired evolutions.\n")
    return active, expired


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
            "psCaps":    item.get("psCaps", []),
            "plus":      item.get("plus", []),
            "plusCaps":  item.get("plusCaps", []),
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

def js_num_array(lst):
    """Format a list of numbers (or None) as a JS array."""
    items = ', '.join('null' if v is None else str(v) for v in lst)
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
        exp_field    = f', "expires": "{evo["expires"]}"' if evo.get('expires') else ''
        ps_field     = js_array(evo.get('ps', []))
        ps_caps_field = f', psCaps: {js_num_array(evo.get("psCaps", []))}' if evo.get('psCaps') else ''
        plus_field   = js_array(evo.get('plus', []))
        plus_caps_field = f', plusCaps: {js_num_array(evo.get("plusCaps", []))}' if evo.get('plusCaps') else ''
        pos_field       = f', pos: "{evo["pos"]}"'           if evo.get("pos")       else ''
        rating_field    = f', maxRating: {evo["maxRating"]}'   if evo.get("maxRating") else ''
        boost_field     = f', ovrBoost: "{evo["ovrBoost"]}"' if evo.get("ovrBoost") else ''
        cap_field       = f', ovrCap: {evo["ovrCap"]}'          if evo.get("ovrCap")   else ''
        new_lines.append(
            f'\n        {{ name: "{evo["name"]}", ps: {ps_field}{ps_caps_field}, plus: {plus_field}{plus_caps_field}, exp: false{exp_field}{pos_field}{rating_field}{boost_field}{cap_field} }},  // AUTO-ADDED'
        )

    # 4. Append new expired evos (scraped from /evolutions/expired, not seen before)
    expired_lines = []
    for evo in diff.get('new_expired', []):
        exp_field    = f', "expires": "{evo["expires"]}"' if evo.get('expires') else ''
        ps_field     = js_array(evo.get('ps', []))
        ps_caps_field_e = f', psCaps: {js_num_array(evo.get("psCaps", []))}' if evo.get('psCaps') else ''
        plus_field   = js_array(evo.get('plus', []))
        plus_caps_field_e = f', plusCaps: {js_num_array(evo.get("plusCaps", []))}' if evo.get('plusCaps') else ''
        pos_field_e    = f', pos: "{evo["pos"]}"'           if evo.get("pos")       else ''
        rating_field_e = f', maxRating: {evo["maxRating"]}'   if evo.get("maxRating") else ''
        boost_field_e  = f', ovrBoost: "{evo["ovrBoost"]}"' if evo.get("ovrBoost") else ''
        cap_field_e    = f', ovrCap: {evo["ovrCap"]}'          if evo.get("ovrCap")   else ''
        expired_lines.append(
            f'\n        {{ name: "{evo["name"]}", ps: {ps_field}{ps_caps_field_e}, plus: {plus_field}{plus_caps_field_e}, exp: true{exp_field}{pos_field_e}{rating_field_e}{boost_field_e}{cap_field_e} }},  // AUTO-ADDED (expired)'
        )

    if new_lines or expired_lines:
        # Strip any existing AUTO-ADDED header at the top of the block to avoid duplicates
        block = re.sub(r'^\s*// ── AUTO-ADDED by sync_evos\.py ──\s*', '', block)
        block = '\n        // ── AUTO-ADDED by sync_evos.py ──' + ''.join(new_lines) + ''.join(expired_lines) + block

    # Ensure ]; lands on its own line — if block ends in a comment the ]; would
    # otherwise be appended to it, making it invisible to the JS parser.
    block = block.rstrip('\n') + '\n    '
    return html[:m.start()] + m.group(1) + block + m.group(3) + html[m.end():]


def inject_ps_cap_display(html):
    """Idempotent: update buildRow to render [icon] cap for each playstyle,
    with base PS in a 5-column auto-fit grid (max 2 rows for 10 icons)."""
    if 'psCaps' in html and 'ps-cap' in html:
        return html  # already patched

    # ── CSS ──────────────────────────────────────────────────────────────────
    OLD_ICON_CSS = '.ps-icon { width: 38px; height: 38px; object-fit: contain; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.5)); }'
    NEW_ICON_CSS = (
        '.ps-icon-wrap { display: inline-flex; flex-direction: column; align-items: center; gap: 2px; }'
        '\n        .ps-icon { width: 32px; height: 32px; object-fit: contain; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.5)); }'
        '\n        .ps-cap { font-size: 0.65rem; color: #fff; font-weight: bold; white-space: nowrap; }'
        '\n        .ps-base-row { display: grid; grid-template-columns: repeat(auto-fit, 32px); max-width: 180px; gap: 5px; }'
    )
    if OLD_ICON_CSS in html:
        html = html.replace(OLD_ICON_CSS, NEW_ICON_CSS)

    # ── icon-row gap ─────────────────────────────────────────────────────────
    OLD_ICON_ROW = '.icon-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }'
    NEW_ICON_ROW = '.icon-row { display: flex; gap: 5px; flex-wrap: wrap; align-items: center; }'
    if OLD_ICON_ROW in html:
        html = html.replace(OLD_ICON_ROW, NEW_ICON_ROW)

    # ── column widths ─────────────────────────────────────────────────────────
    html = html.replace(
        'style="width: 30%;" onclick="sortBy(\'name\')"',
        'style="width: 20%;" onclick="sortBy(\'name\')"'
    )
    html = html.replace(
        'data-col="ps"        onclick="sortBy(\'ps\')"',
        'data-col="ps"        style="width: 26%;" onclick="sortBy(\'ps\')"'
    )
    html = html.replace(
        'data-col="plus"      onclick="sortBy(\'plus\')"',
        'data-col="plus"      style="width: 20%;" onclick="sortBy(\'plus\')"'
    )

    # ── JS: base playstyles cell uses ps-base-row grid ────────────────────────
    OLD_PS_TD = '<td><div class="icon-row">${psHTML}</div></td>'
    NEW_PS_TD = '<td><div class="icon-row ps-base-row">${psHTML}</div></td>'
    if OLD_PS_TD in html:
        html = html.replace(OLD_PS_TD, NEW_PS_TD)

    # ── JS: base playstyle map function ───────────────────────────────────────
    OLD_PS = (
        "        const psHTML = evo.ps.length > 0 ? evo.ps.map(p => {\n"
        "            const d = playstyleMap[p];\n"
        "            return d ? `<img src=\"${d.folder}/${d.file}_standard.png\" class=\"ps-icon\" title=\"${p}\">` : `<span>${p}</span>`;\n"
        "        }).join('') : '<span class=\"no-data\">N/A</span>';"
    )
    NEW_PS = (
        "        const psHTML = evo.ps.length > 0 ? evo.ps.map((p, i) => {\n"
        "            const d = playstyleMap[p];\n"
        "            const cap = (evo.psCaps || [])[i];\n"
        "            const capStr = cap != null ? `<span class=\"ps-cap\">${cap}</span>` : '';\n"
        "            return d ? `<span class=\"ps-icon-wrap\"><img src=\"${d.folder}/${d.file}_standard.png\" class=\"ps-icon\" title=\"${p}\">${capStr}</span>` : `<span>${p}</span>`;\n"
        "        }).join('') : '<span class=\"no-data\">N/A</span>';"
    )
    if OLD_PS in html:
        html = html.replace(OLD_PS, NEW_PS)

    # ── JS: plus playstyle map function ───────────────────────────────────────
    OLD_PLUS = (
        "        const plusHTML = evo.plus.length > 0 ? evo.plus.map(p => {\n"
        "            const d = playstyleMap[p];\n"
        "            return d ? `<img src=\"${d.folder}/${d.file}_plus.png\" class=\"ps-icon plus-icon\" title=\"${p}+\">` : `<span>${p}+</span>`;\n"
        "        }).join('') : '<span class=\"no-data\">N/A</span>';"
    )
    NEW_PLUS = (
        "        const plusHTML = evo.plus.length > 0 ? evo.plus.map((p, i) => {\n"
        "            const d = playstyleMap[p];\n"
        "            const cap = (evo.plusCaps || [])[i];\n"
        "            const capStr = cap != null ? `<span class=\"ps-cap\">${cap}</span>` : '';\n"
        "            return d ? `<span class=\"ps-icon-wrap\"><img src=\"${d.folder}/${d.file}_plus.png\" class=\"ps-icon plus-icon\" title=\"${p}+\">${capStr}</span>` : `<span>${p}+</span>`;\n"
        "        }).join('') : '<span class=\"no-data\">N/A</span>';"
    )
    if OLD_PLUS in html:
        html = html.replace(OLD_PLUS, NEW_PLUS)

    return html


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
        updated_html = inject_ps_cap_display(updated_html)
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
