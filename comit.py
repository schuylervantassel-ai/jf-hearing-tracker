#!/usr/bin/env python3
"""
Congressional Hearing Tracker - Jamestown Foundation
Tracks hearings across key national security committees,
with automatic RSS feed pulling.

Requirements:
    pip install feedparser openpyxl
"""

import json
import os
import re
import ssl
import sys
from datetime import datetime, date
from urllib.request import urlopen, Request
from urllib.error import URLError
import xml.etree.ElementTree as ET

# ── Optional feedparser (better date parsing) ─────────────────────────────────
try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

# ── Storage ───────────────────────────────────────────────────────────────────
# Set DATA_DIR (e.g. /var/data on Render) for persistent disk; defaults to this folder.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_ROOT = os.environ.get("DATA_DIR", "").strip() or _SCRIPT_DIR

def _data_path(filename: str) -> str:
    return os.path.join(_DATA_ROOT, filename)

DATA_FILE    = _data_path("hearings.json")
CONFIG_FILE  = _data_path("rss_config.json")
SOCIAL_FILE  = _data_path("social_feed.json")
SOCIAL_LIMIT = 500   # max items to keep across all social feeds

# ── RSS Feeds ─────────────────────────────────────────────────────────────────
DEFAULT_FEEDS = [
    {
        "name": "Senate Armed Services (SASC)",
        "url": "https://rss.app/feeds/TQ2HZ3EcaUZdjfZk.xml",
        "committee": "Senate Armed Services (SASC)",
        "active": True,
    },
    {
        "name": "Senate Foreign Relations (SFRC)",
        "url": "https://rss.app/feeds/52g7oTFDxPrMSp15.xml",
        "committee": "Senate Foreign Relations (SFRC)",
        "active": True,
    },
    {
        "name": "Senate Intelligence (SSCI)",
        "url": "https://rss.app/feeds/Wk9rFjawif2PF1cC.xml",
        "committee": "Senate Intelligence (SSCI)",
        "active": True,
    },
    {
        "name": "Senate Homeland Security (SHSGAC)",
        "url": "https://rss.app/feeds/viBWi7HQxZLlJ85m.xml",
        "committee": "Senate Homeland Security (SHSGAC)",
        "active": True,
    },
    {
        "name": "House Armed Services (HASC)",
        "url": "https://armedservices.house.gov/rss.xml",
        "committee": "House Armed Services (HASC)",
        "active": False,  # No public RSS feed available; add manually
    },
    {
        "name": "House Foreign Affairs (HFAC)",
        "url": "https://rss.app/feeds/iqYqfkbDWR3Q2Y4i.xml",
        "committee": "House Foreign Affairs (HFAC)",
        "active": True,
    },
    {
        "name": "House Intelligence (HPSCI)",
        "url": "https://intelligence.house.gov/feed/",
        "committee": "House Intelligence (HPSCI)",
        "active": True,
    },
    {
        "name": "House Homeland Security (HHSC)",
        "url": "https://homeland.house.gov/feed/",
        "committee": "House Homeland Security (HHSC)",
        "active": True,
    },
    {
        "name": "GovTrack - Committee Hearings",
        "url": "https://www.govtrack.us/congress/committees/hearings/feed",
        "committee": "Multiple",
        "active": False,  # Feed removed by GovTrack
    },
    {
        "name": "GovInfo - All Congressional Hearings",
        "url": "https://www.govinfo.gov/rss/chrg.xml",
        "committee": "Multiple",
        "active": True,
    },
]

# Social / X (Twitter) feeds — tracked separately from hearing RSS feeds
# url="" means not yet configured; set active=True once a url is added.
DEFAULT_SOCIAL_FEEDS = [
    {
        "name": "SASC on X",
        "handle": "@ArmedServices",
        "committee": "Senate Armed Services (SASC)",
        "url": "",
        "active": False,
    },
    {
        "name": "SFRC on X",
        "handle": "@SenateForeign",
        "committee": "Senate Foreign Relations (SFRC)",
        "url": "",
        "active": False,
    },
    {
        "name": "SSCI on X",
        "handle": "@SenIntelComm",
        "committee": "Senate Intelligence (SSCI)",
        "url": "",
        "active": False,
    },
    {
        "name": "SHSGAC on X",
        "handle": "@SenHomeland",
        "committee": "Senate Homeland Security (SHSGAC)",
        "url": "",
        "active": False,
    },
    {
        "name": "HASC on X",
        "handle": "@HASCRepublicans",
        "committee": "House Armed Services (HASC)",
        "url": "",
        "active": False,
    },
    {
        "name": "HFAC Majority on X",
        "handle": "@HouseForeignGOP",
        "committee": "House Foreign Affairs (HFAC)",
        "url": "https://rss.app/feeds/wJ2Wr7h4hpDCsOgi.xml",
        "active": True,
    },
    {
        "name": "HPSCI on X",
        "handle": "@HouseIntelGOP",
        "committee": "House Intelligence (HPSCI)",
        "url": "",
        "active": False,
    },
    {
        "name": "HHSC on X",
        "handle": "@HomelandGOP",
        "committee": "House Homeland Security (HHSC)",
        "url": "",
        "active": False,
    },
]

SOCIAL_CONFIG_FILE = _data_path("social_config.json")

COMMITTEES = [
    "Senate Armed Services (SASC)",
    "Senate Foreign Relations (SFRC)",
    "Senate Intelligence (SSCI)",
    "Senate Homeland Security (SHSGAC)",
    "House Armed Services (HASC)",
    "House Foreign Affairs (HFAC)",
    "House Intelligence (HPSCI)",
    "House Homeland Security (HHSC)",
    "Other",
]

JAMESTOWN_ANGLES = [
    "Russia/Eurasia",
    "China/Indo-Pacific",
    "Middle East/North Africa",
    "Sub-Saharan Africa",
    "Terrorism/Extremism",
    "Central Asia",
    "Latin America",
    "Cyber/Information Warfare",
    "Other",
]

ACTIONS = [
    "Send brief",
    "Send questions",
    "Offer testimony",
    "Request meeting",
    "Monitor only",
    "No action needed",
]

STATUS_OPTIONS = ["Upcoming", "Completed", "Cancelled", "Postponed"]

# Keywords that auto-flag a hearing's Jamestown angle
RELEVANCE_KEYWORDS = {
    "Russia/Eurasia": ["russia", "ukraine", "nato", "eurasia", "belarus", "moldova",
                       "caucasus", "georgia", "kremlin", "wagner", "putin"],
    "China/Indo-Pacific": ["china", "taiwan", "indo-pacific", "pla", "beijing",
                            "south china sea", "xinjiang", "tibet", "hong kong"],
    "Middle East/North Africa": ["iran", "iraq", "syria", "yemen", "israel", "hamas",
                                  "hezbollah", "mena", "saudi", "gulf", "libya", "egypt"],
    "Sub-Saharan Africa": ["africa", "sahel", "mali", "niger", "nigeria", "somalia",
                            "al-shabaab", "sudan", "ethiopia"],
    "Terrorism/Extremism": ["terrorism", "isis", "al-qaeda", "extremism", "jihadist",
                             "counterterrorism", "violent extremism", "radicalization"],
    "Central Asia": ["kazakhstan", "uzbekistan", "tajikistan", "kyrgyzstan",
                     "turkmenistan", "afghanistan", "central asia"],
    "Latin America": ["venezuela", "cuba", "nicaragua", "cartel", "narco",
                      "latin america", "mexico", "colombia"],
    "Cyber/Information Warfare": ["cyber", "disinformation", "information warfare",
                                   "influence operation", "hack", "ransomware", "espionage"],
}

# ── Data helpers ──────────────────────────────────────────────────────────────

def auto_close_past_hearings(hearings):
    """
    Set status to 'Completed' for any hearing that was 'Upcoming'
    but whose date is strictly before today. Modifies list in place
    and returns the number of records changed.
    """
    today = date.today().isoformat()
    changed = 0
    for h in hearings:
        if h.get("status") == "Upcoming" and h.get("date", "9999") < today:
            h["status"] = "Completed"
            changed += 1
    return changed

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            hearings = json.load(f)
        # Auto-close any hearings whose date has passed
        if auto_close_past_hearings(hearings):
            save_data(hearings)
        return hearings
    return []

def save_data(hearings):
    with open(DATA_FILE, "w") as f:
        json.dump(hearings, f, indent=2)

def load_feeds():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    save_feeds(DEFAULT_FEEDS)
    return DEFAULT_FEEDS

def save_feeds(feeds):
    with open(CONFIG_FILE, "w") as f:
        json.dump(feeds, f, indent=2)

def load_social_feeds():
    if not os.path.exists(SOCIAL_CONFIG_FILE):
        save_social_feeds(DEFAULT_SOCIAL_FEEDS)
        return [dict(f) for f in DEFAULT_SOCIAL_FEEDS]
    with open(SOCIAL_CONFIG_FILE) as f:
        saved = json.load(f)
    # Merge: add any DEFAULT entries whose committee isn't represented yet
    saved_committees = {f["committee"] for f in saved}
    changed = False
    for default in DEFAULT_SOCIAL_FEEDS:
        if default["committee"] not in saved_committees:
            saved.append(dict(default))
            changed = True
    if changed:
        save_social_feeds(saved)
    return saved

def save_social_feeds(feeds):
    with open(SOCIAL_CONFIG_FILE, "w") as f:
        json.dump(feeds, f, indent=2)

def load_social_items():
    if os.path.exists(SOCIAL_FILE):
        with open(SOCIAL_FILE) as f:
            return json.load(f)
    return []

def save_social_items(items):
    with open(SOCIAL_FILE, "w") as f:
        json.dump(items, f, indent=2)

def next_id(hearings):
    return max((h["id"] for h in hearings), default=0) + 1

# ── Display helpers ───────────────────────────────────────────────────────────

def divider(char="─", width=72):
    print(char * width)

def header(title):
    print()
    divider("═")
    print(f"  {title}")
    divider("═")

def pick(prompt, options, allow_blank=False):
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    if allow_blank:
        print("  [Enter to skip]")
    while True:
        raw = input("  Choice: ").strip()
        if allow_blank and raw == "":
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print("  Invalid choice, try again.")

def ask(prompt, required=True, default=None):
    hint = f" [{default}]" if default else ""
    while True:
        val = input(f"  {prompt}{hint}: ").strip()
        if val:
            return val
        if default:
            return default
        if not required:
            return ""
        print("  This field is required.")

def ask_date(prompt, required=True):
    while True:
        raw = input(f"  {prompt} (YYYY-MM-DD): ").strip()
        if not raw and not required:
            return None
        try:
            datetime.strptime(raw, "%Y-%m-%d")
            return raw
        except ValueError:
            print("  Invalid date. Use YYYY-MM-DD.")

def days_away_str(date_str):
    try:
        delta = (date.fromisoformat(date_str) - date.today()).days
        if delta == 0:
            return " <- TODAY"
        elif delta > 0:
            return f" (in {delta}d)"
        else:
            return f" ({abs(delta)}d ago)"
    except Exception:
        return ""

def format_hearing(h, verbose=False):
    source_tag = " [RSS]" if h.get("source") == "rss" else " [Manual]"
    print(f"\n  ID {h['id']:03d} | {h['date']}{days_away_str(h['date'])} | [{h.get('status', 'Upcoming')}]{source_tag}")
    print(f"  Committee : {h['committee']}")
    print(f"  Topic     : {h['topic']}")
    if h.get("witnesses"):
        print(f"  Witnesses : {h['witnesses']}")
    if h.get("url"):
        print(f"  Link      : {h['url']}")
    print(f"  Angle     : {h.get('angle', '--')}")
    print(f"  Action    : {h.get('action', '--')}")
    if verbose:
        if h.get("questions"):
            print(f"\n  Questions to ask:")
            for q in h["questions"].split("|"):
                q = q.strip()
                if q:
                    print(f"    * {q}")
        if h.get("notes"):
            print(f"\n  Notes     : {h['notes']}")
    divider()

# ── RSS Parsing ───────────────────────────────────────────────────────────────

def detect_angle(text):
    text_lower = text.lower()
    for angle, keywords in RELEVANCE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return angle
    return "Other"

def parse_date_str(date_str):
    if not date_str:
        return date.today().isoformat()
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
        "%B %d, %Y",
        "%b %d, %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    if HAS_FEEDPARSER:
        parsed = feedparser._parse_date(date_str)
        if parsed:
            return date(*parsed[:3]).isoformat()
    return date.today().isoformat()

def clean_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()

def _congress_year(n):
    """Return the start year of the Nth Congress (119th → 2025)."""
    return 2025 - 2 * (119 - n)

def _extract_congress_date(title, url):
    """
    Some feeds (e.g. GovInfo) assign today's pubDate to old records they've
    just digitised.  Detect the actual hearing era from the Congress number
    embedded in the title or URL and return the END date of that Congress's
    term — so the filter only rejects items where the entire Congress is
    older than the cutoff.

    Examples:
      CHRG-119... → 119th Congress (2025-2027, ongoing) → today's date → KEEP
      CHRG-118... → 118th Congress ended Jan 2025 → '2025-01-03' → SKIP if >90d
      CHRG-117... → 117th Congress ended Jan 2023 → '2023-01-03' → SKIP

    Returns None if no Congress number is detected.
    """
    combined = f"{title or ''} {url or ''}"
    for pat in (
        r"CHRG-(\d{2,3})[a-z]",              # CHRG-119hhrg… / CHRG-117shrg…
        r"[Hh]rg[.\s]+(\d{3})\s*[-\u2013]",  # S. Hrg. 119-… / Hrg. 117-…
        r"(\d{3})(?:st|nd|rd|th)\s+[Cc]ongress",  # 119th Congress
    ):
        m = re.search(pat, combined)
        if m:
            n = int(m.group(1))
            if 80 <= n <= 130:  # sanity check
                end_date = date(_congress_year(n) + 2, 1, 3)
                # If the Congress is still ongoing, use today so it always passes
                if end_date > date.today():
                    end_date = date.today()
                return end_date.isoformat()
    return None

def is_duplicate(hearings, title, committee):
    title_lower = title.lower().strip()
    for h in hearings:
        if h["committee"] == committee and h["topic"].lower().strip() == title_lower:
            return True
    return False

def _make_ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    ctx = ssl.create_default_context()
    try:
        ctx.load_default_certs()
    except Exception:
        pass
    return ctx

def fetch_feed_raw(url):
    headers = {"User-Agent": "Mozilla/5.0 (Jamestown Foundation Hearing Tracker)"}
    req = Request(url, headers=headers)
    ctx = _make_ssl_context()
    try:
        with urlopen(req, timeout=10, context=ctx) as resp:
            content = resp.read()
    except ssl.SSLCertVerificationError:
        fallback = ssl.create_default_context()
        fallback.check_hostname = False
        fallback.verify_mode = ssl.CERT_NONE
        with urlopen(req, timeout=10, context=fallback) as resp:
            content = resp.read()

    if HAS_FEEDPARSER:
        feed = feedparser.parse(content)
        items = []
        for entry in feed.entries:
            items.append({
                "title":   entry.get("title", ""),
                "date":    entry.get("published", entry.get("updated", "")),
                "url":     entry.get("link", ""),
                "summary": entry.get("summary", entry.get("description", "")),
            })
        return items

    # Fallback: raw XML
    root = ET.fromstring(content)
    ns   = {"atom": "http://www.w3.org/2005/Atom"}
    items = []
    for item in root.findall(".//item"):
        items.append({
            "title":   item.findtext("title", ""),
            "date":    item.findtext("pubDate", ""),
            "url":     item.findtext("link", ""),
            "summary": item.findtext("description", ""),
        })
    if not items:
        for entry in root.findall(".//atom:entry", ns):
            link_el = entry.find("atom:link", ns)
            items.append({
                "title":   entry.findtext("atom:title", "", ns),
                "date":    entry.findtext("atom:updated", "", ns),
                "url":     link_el.get("href", "") if link_el is not None else "",
                "summary": entry.findtext("atom:summary", "", ns),
            })
    return items

RSS_CUTOFF_DAYS = 90   # ignore feed items older than this

def pull_rss_feeds(hearings, feeds, silent=False):
    new_items = []
    cutoff = date.today().toordinal() - RSS_CUTOFF_DAYS

    for feed in feeds:
        if not feed.get("active", True):
            continue
        if not silent:
            print(f"  Fetching: {feed['name']} ... ", end="", flush=True)
        try:
            items = fetch_feed_raw(feed["url"])
            added = 0
            skipped_old = 0
            for item in items:
                title   = clean_html(item["title"])
                summary = clean_html(item["summary"])
                if not title:
                    continue
                # Drop items older than the cutoff (by pubDate)
                item_date_str = parse_date_str(item["date"])
                try:
                    item_ord = date.fromisoformat(item_date_str).toordinal()
                except Exception:
                    item_ord = cutoff
                if item_ord < cutoff:
                    skipped_old += 1
                    continue

                # Secondary check: detect actual hearing era from Congress
                # number in URL/title (GovInfo backfills old records with
                # current pubDates, so pubDate alone is not enough).
                content_date = _extract_congress_date(title, item.get("url", ""))
                if content_date:
                    try:
                        if date.fromisoformat(content_date).toordinal() < cutoff:
                            skipped_old += 1
                            continue
                    except Exception:
                        pass

                if is_duplicate(hearings + new_items, title, feed["committee"]):
                    continue
                angle = detect_angle(f"{title} {summary}")
                item_date_resolved = parse_date_str(item["date"])
                auto_status = "Completed" if item_date_resolved < date.today().isoformat() else "Upcoming"
                h = {
                    "id":        next_id(hearings + new_items),
                    "date":      item_date_resolved,
                    "committee": feed["committee"],
                    "topic":     title,
                    "witnesses": "",
                    "angle":     angle,
                    "action":    "Monitor only",
                    "status":    auto_status,
                    "questions": "",
                    "notes":     summary[:300] if summary else "",
                    "url":       item.get("url", ""),
                    "source":    "rss",
                    "created":   datetime.now().strftime("%Y-%m-%d"),
                }
                new_items.append(h)
                hearings.append(h)
                added += 1
            if not silent:
                old_note = f", {skipped_old} too old" if skipped_old else ""
                print(f"{added} new item(s){old_note}")
            feed["last_fetched"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            feed["last_status"]  = "OK"
        except URLError as e:
            if not silent:
                print(f"FAILED (network: {e.reason})")
            feed["last_status"] = f"Error: {e.reason}"
        except Exception as e:
            if not silent:
                print(f"FAILED ({e})")
            feed["last_status"] = f"Error: {e}"

    save_data(hearings)
    save_feeds(feeds)
    return new_items

# ── Social / X Feed Pulling ───────────────────────────────────────────────────

def _strip_tweet_html(text):
    """Remove embedded blockquote/script tags from rss.app Twitter descriptions."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
    text = re.sub(r"<blockquote[^>]*>", "", text)
    text = re.sub(r"</blockquote>", "", text)
    text = clean_html(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def pull_social_feeds(social_feeds=None, silent=False):
    """
    Fetch X / Twitter rss.app feeds and store items in social_feed.json.
    Returns a list of newly added items.
    """
    if social_feeds is None:
        social_feeds = load_social_feeds()

    existing_items = load_social_items()
    existing_urls  = {item["url"] for item in existing_items}
    cutoff = date.today().toordinal() - RSS_CUTOFF_DAYS
    new_items = []

    for feed in social_feeds:
        if not feed.get("active", True) or not feed.get("url", "").strip():
            continue
        if not silent:
            print(f"  Social feed: {feed['name']} ... ", end="", flush=True)
        added = 0
        try:
            raw_items = fetch_feed_raw(feed["url"])
            for item in raw_items:
                url = item.get("url", "")
                if not url or url in existing_urls:
                    continue

                item_date_str = parse_date_str(item["date"])
                try:
                    if date.fromisoformat(item_date_str).toordinal() < cutoff:
                        continue
                except Exception:
                    pass

                title   = clean_html(item.get("title", "")).strip()
                summary = _strip_tweet_html(item.get("summary", ""))
                if not title:
                    title = summary[:120]

                # Skip pure retweet noise with no text
                if not title and not summary:
                    continue

                social_item = {
                    "url":       url,
                    "title":     title,
                    "summary":   summary,
                    "date":      item_date_str,
                    "committee": feed.get("committee", "Other"),
                    "feed_name": feed["name"],
                    "author":    item.get("author", ""),
                    "fetched":   datetime.now().strftime("%Y-%m-%d"),
                }
                new_items.append(social_item)
                existing_urls.add(url)
                added += 1

            feed["last_fetched"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            feed["last_status"]  = "OK"
            if not silent:
                print(f"{added} new item(s)")
        except Exception as e:
            if not silent:
                print(f"FAILED ({e})")
            feed["last_status"] = f"Error: {e}"

    if new_items:
        combined = new_items + existing_items
        # Keep most recent SOCIAL_LIMIT items
        combined.sort(key=lambda x: x.get("date", ""), reverse=True)
        save_social_items(combined[:SOCIAL_LIMIT])

    save_social_feeds(social_feeds)
    return new_items

# ── Congress.gov API ──────────────────────────────────────────────────────────

CONGRESS_API_BASE    = "https://api.congress.gov/v3"
CONGRESS_API_CURRENT = 119   # update when a new Congress begins

# Maps Congress.gov committee systemCode → app committee label
CONGRESS_API_COMMITTEES = {
    "ssas00": "Senate Armed Services (SASC)",
    "ssfr00": "Senate Foreign Relations (SFRC)",
    "slin00": "Senate Intelligence (SSCI)",
    "ssga00": "Senate Homeland Security (SHSGAC)",
    "hsas00": "House Armed Services (HASC)",
    "hsfa00": "House Foreign Affairs (HFAC)",
    "hlig00": "House Intelligence (HPSCI)",
    "hshm00": "House Homeland Security (HHSC)",
}

def fetch_json(url, api_key):
    """GET a URL from the Congress.gov API and return parsed JSON."""
    sep = "&" if "?" in url else "?"
    full_url = f"{url}{sep}api_key={api_key}&format=json"
    headers = {"User-Agent": "Mozilla/5.0 (Jamestown Foundation Hearing Tracker)"}
    req = Request(full_url, headers=headers)
    ctx = _make_ssl_context()
    with urlopen(req, timeout=20, context=ctx) as resp:
        return json.loads(resp.read())

def pull_congress_api(hearings, api_key, silent=False):
    """
    Pull scheduled committee meetings from the Congress.gov API
    (/v3/committee-meeting) and add any new hearings for tracked committees.
    Returns a list of newly added hearing dicts.
    """
    if not api_key or not api_key.strip():
        if not silent:
            print("  Congress.gov API: no key configured — skipping.")
        return []

    new_items = []
    cutoff = date.today().toordinal() - RSS_CUTOFF_DAYS
    existing_ids = {h.get("congress_event_id") for h in hearings
                    if h.get("congress_event_id")}

    for chamber in ("house", "senate"):
        if not silent:
            print(f"  Congress.gov API ({chamber}) ... ", end="", flush=True)
        added = 0
        try:
            list_url = (f"{CONGRESS_API_BASE}/committee-meeting/"
                        f"{CONGRESS_API_CURRENT}/{chamber}?limit=50")
            data     = fetch_json(list_url, api_key)
            meetings = data.get("committeeMeetings", [])

            for mtg in meetings:
                event_id = str(mtg.get("eventId", ""))
                if not event_id or event_id in existing_ids:
                    continue

                detail_url = mtg.get("url", "")
                if not detail_url:
                    continue

                try:
                    detail = fetch_json(detail_url, api_key)
                    m = detail.get("committeeMeeting", {})
                except Exception:
                    continue

                # Match to a tracked committee
                committee_name = None
                for c in m.get("committees", []):
                    sc = c.get("systemCode", "")
                    if sc in CONGRESS_API_COMMITTEES:
                        committee_name = CONGRESS_API_COMMITTEES[sc]
                        break
                if not committee_name:
                    continue

                # Parse the earliest listed meeting date
                meeting_date = None
                for d in m.get("dates", []):
                    raw = (d.get("date") or "")[:10]
                    if raw:
                        meeting_date = raw
                        break
                if not meeting_date:
                    continue

                # Age filter
                try:
                    if date.fromisoformat(meeting_date).toordinal() < cutoff:
                        continue
                except Exception:
                    pass

                title = (m.get("title") or "").strip()
                if not title:
                    meeting_type = m.get("type") or "Meeting"
                    title = f"{committee_name} – {meeting_type}"

                if is_duplicate(hearings + new_items, title, committee_name):
                    continue

                # Witnesses → semicolon-separated names
                witnesses = "; ".join(
                    w.get("name", "") for w in m.get("witnesses", [])
                    if w.get("name")
                )

                # Status — also auto-close if the meeting date has passed
                api_status = m.get("status", "Scheduled")
                status = {
                    "Scheduled":   "Upcoming",
                    "Canceled":    "Cancelled",
                    "Postponed":   "Postponed",
                    "Rescheduled": "Upcoming",
                }.get(api_status, "Upcoming")
                if status == "Upcoming" and meeting_date < date.today().isoformat():
                    status = "Completed"

                # Location (first continuation block)
                notes_parts = []
                for cont in m.get("meetingContinuations", []):
                    loc = cont.get("location") or {}
                    room     = loc.get("room", "")
                    building = loc.get("building", "")
                    if room or building:
                        notes_parts.append(f"{room} {building}".strip())
                    break
                # Attach any related bill numbers to notes
                for bill in (m.get("relatedItems") or {}).get("bills", []):
                    num = bill.get("number", "")
                    btype = bill.get("type", "")
                    if num and btype:
                        notes_parts.append(f"{btype} {num}")

                h = {
                    "id":                next_id(hearings + new_items),
                    "date":              meeting_date,
                    "committee":         committee_name,
                    "topic":             title,
                    "witnesses":         witnesses,
                    "angle":             detect_angle(title),
                    "action":            "Monitor only",
                    "status":            status,
                    "questions":         "",
                    "notes":             "; ".join(notes_parts),
                    "url":               (f"https://www.congress.gov/committee-meeting/"
                                          f"{CONGRESS_API_CURRENT}/{chamber}/{event_id}"),
                    "source":            "api",
                    "congress_event_id": event_id,
                    "created":           datetime.now().strftime("%Y-%m-%d"),
                }
                new_items.append(h)
                hearings.append(h)
                existing_ids.add(event_id)
                added += 1

            if not silent:
                print(f"{added} new item(s)")
        except Exception as e:
            if not silent:
                print(f"FAILED ({e})")

    if new_items:
        save_data(hearings)
    return new_items

# ── CRUD ──────────────────────────────────────────────────────────────────────

def add_hearing(hearings):
    header("ADD HEARING")
    h = {
        "id":        next_id(hearings),
        "date":      ask_date("Date"),
        "committee": pick("Committee:", COMMITTEES),
        "topic":     ask("Hearing topic"),
        "witnesses": ask("Witnesses (optional)", required=False),
        "angle":     pick("Jamestown angle:", JAMESTOWN_ANGLES),
        "action":    pick("Recommended action:", ACTIONS),
        "status":    pick("Status:", STATUS_OPTIONS),
        "url":       ask("Link/URL (optional)", required=False),
        "source":    "manual",
        "created":   datetime.now().strftime("%Y-%m-%d"),
    }
    print("\n  Questions to ask (one per line, blank to finish):")
    questions = []
    while True:
        q = input("  Q: ").strip()
        if not q:
            break
        questions.append(q)
    h["questions"] = " | ".join(questions)
    h["notes"]     = ask("Additional notes (optional)", required=False)
    hearings.append(h)
    save_data(hearings)
    print(f"\n  Hearing #{h['id']:03d} added.")

def list_hearings(hearings, filter_status=None):
    if not hearings:
        print("\n  No hearings tracked yet.")
        return
    filtered = sorted(
        [h for h in hearings if not filter_status or h.get("status") == filter_status],
        key=lambda x: x["date"]
    )
    print(f"\n  Showing {len(filtered)} hearing(s):")
    divider()
    for h in filtered:
        format_hearing(h)

def view_hearing(hearings):
    hid = input("\n  Enter hearing ID: ").strip()
    if not hid.isdigit():
        print("  Invalid ID.")
        return
    matches = [h for h in hearings if h["id"] == int(hid)]
    if not matches:
        print("  Hearing not found.")
        return
    format_hearing(matches[0], verbose=True)

def edit_hearing(hearings):
    hid = input("\n  Enter hearing ID to edit: ").strip()
    if not hid.isdigit():
        print("  Invalid ID.")
        return
    matches = [h for h in hearings if h["id"] == int(hid)]
    if not matches:
        print("  Hearing not found.")
        return
    h = matches[0]
    format_hearing(h)
    print("  Press Enter to keep current value.\n")

    new_date = ask_date(f"Date [{h['date']}]", required=False)
    if new_date:
        h["date"] = new_date

    print(f"\n  Current committee: {h['committee']}")
    if input("  Change committee? (y/N): ").strip().lower() == "y":
        h["committee"] = pick("Committee:", COMMITTEES)

    new_topic = ask(f"Topic [{h['topic']}]", required=False)
    if new_topic:
        h["topic"] = new_topic

    new_w = ask(f"Witnesses [{h.get('witnesses', '')}]", required=False)
    if new_w:
        h["witnesses"] = new_w

    print(f"\n  Current angle: {h.get('angle', '--')}")
    if input("  Change angle? (y/N): ").strip().lower() == "y":
        h["angle"] = pick("Jamestown angle:", JAMESTOWN_ANGLES)

    print(f"\n  Current action: {h.get('action', '--')}")
    if input("  Change action? (y/N): ").strip().lower() == "y":
        h["action"] = pick("Recommended action:", ACTIONS)

    print(f"\n  Current status: {h.get('status', '--')}")
    if input("  Change status? (y/N): ").strip().lower() == "y":
        h["status"] = pick("Status:", STATUS_OPTIONS)

    if input("\n  Update questions? (y/N): ").strip().lower() == "y":
        print("  Enter questions (blank to finish):")
        questions = []
        while True:
            q = input("  Q: ").strip()
            if not q:
                break
            questions.append(q)
        h["questions"] = " | ".join(questions)

    new_notes = ask(f"Notes [{h.get('notes', '')}]", required=False)
    if new_notes:
        h["notes"] = new_notes

    save_data(hearings)
    print(f"\n  Hearing #{h['id']:03d} updated.")

def delete_hearing(hearings):
    hid = input("\n  Enter hearing ID to delete: ").strip()
    if not hid.isdigit():
        print("  Invalid ID.")
        return
    matches = [h for h in hearings if h["id"] == int(hid)]
    if not matches:
        print("  Hearing not found.")
        return
    format_hearing(matches[0])
    if input("  Delete this hearing? (yes/N): ").strip().lower() == "yes":
        hearings[:] = [h for h in hearings if h["id"] != int(hid)]
        save_data(hearings)
        print("  Deleted.")
    else:
        print("  Cancelled.")

def search_hearings(hearings):
    term = input("\n  Search term: ").strip().lower()
    if not term:
        return
    results = sorted(
        [h for h in hearings if any(
            term in h.get(f, "").lower()
            for f in ["topic", "committee", "angle", "witnesses", "notes"]
        )],
        key=lambda x: x["date"]
    )
    print(f"\n  Found {len(results)} match(es):")
    divider()
    for h in results:
        format_hearing(h)

def upcoming_summary(hearings):
    header("NEXT 14 DAYS")
    today_ord  = date.today().toordinal()
    cutoff_ord = today_ord + 14
    upcoming = sorted(
        [h for h in hearings
         if h.get("status") in ("Upcoming", None)
         and today_ord <= date.fromisoformat(h["date"]).toordinal() <= cutoff_ord],
        key=lambda x: x["date"]
    )
    if not upcoming:
        print("\n  No upcoming hearings in the next 14 days.")
    else:
        for h in upcoming:
            format_hearing(h, verbose=True)

def manage_feeds(hearings, feeds):
    while True:
        header("RSS FEED MANAGEMENT")
        for i, f in enumerate(feeds, 1):
            status     = "ON " if f.get("active", True) else "OFF"
            last_fetch = f.get("last_fetched", "never")
            last_ok    = f.get("last_status", "--")
            print(f"  {i:2}. [{status}] {f['name']}")
            print(f"        Last: {last_fetch} | {last_ok}")
        divider()
        print("  A. Pull all feeds now")
        print("  T. Toggle feed on/off")
        print("  N. Add custom feed")
        print("  D. Delete feed")
        print("  B. Back")
        divider()
        choice = input("  Select: ").strip().upper()

        if choice == "A":
            print()
            new_items = pull_rss_feeds(hearings, feeds)
            print(f"\n  Done. {len(new_items)} new hearing(s) added.")

        elif choice == "T":
            idx = input("  Feed number to toggle: ").strip()
            if idx.isdigit() and 1 <= int(idx) <= len(feeds):
                f = feeds[int(idx) - 1]
                f["active"] = not f.get("active", True)
                save_feeds(feeds)
                print(f"  {f['name']} {'enabled' if f['active'] else 'disabled'}.")
            else:
                print("  Invalid selection.")

        elif choice == "N":
            print()
            url  = ask("Feed URL")
            name = ask("Display name")
            comm = pick("Map to committee:", COMMITTEES + ["Multiple"])
            feeds.append({"name": name, "url": url, "committee": comm, "active": True})
            save_feeds(feeds)
            print(f"  Feed '{name}' added.")

        elif choice == "D":
            idx = input("  Feed number to delete: ").strip()
            if idx.isdigit() and 1 <= int(idx) <= len(feeds):
                removed = feeds.pop(int(idx) - 1)
                save_feeds(feeds)
                print(f"  Removed '{removed['name']}'.")
            else:
                print("  Invalid selection.")

        elif choice == "B":
            break

def export_to_excel(hearings):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("  Run: pip install openpyxl")
        return

    wb = Workbook()
    ws = wb.active
    ws.title = "Hearing Tracker"

    headers = ["ID", "Date", "Days Away", "Status", "Source", "Committee",
               "Topic", "Witnesses", "Angle", "Action", "Questions", "Link", "Notes"]
    hdr_fill = PatternFill("solid", start_color="1F3864")
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = Font(bold=True, color="FFFFFF", name="Arial")
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    alt_fill = PatternFill("solid", start_color="DCE6F1")
    rss_fill = PatternFill("solid", start_color="E2EFDA")

    for row_num, h in enumerate(sorted(hearings, key=lambda x: x["date"]), 2):
        try:
            delta = (date.fromisoformat(h["date"]) - date.today()).days
            days_away = "Today" if delta == 0 else (f"In {delta}d" if delta > 0 else f"{abs(delta)}d ago")
        except Exception:
            days_away = ""

        is_rss    = h.get("source") == "rss"
        questions = h.get("questions", "").replace(" | ", "\n")
        row = [h["id"], h["date"], days_away, h.get("status", ""),
               "RSS" if is_rss else "Manual",
               h["committee"], h["topic"], h.get("witnesses", ""),
               h.get("angle", ""), h.get("action", ""), questions,
               h.get("url", ""), h.get("notes", "")]

        fill = rss_fill if is_rss else (alt_fill if row_num % 2 == 0 else None)
        for col, val in enumerate(row, 1):
            cell = ws.cell(row=row_num, column=col, value=val)
            cell.font = Font(name="Arial", size=10)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if fill:
                cell.fill = fill

    widths = [5, 12, 10, 12, 8, 30, 42, 28, 22, 18, 40, 35, 35]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.row_dimensions[1].height = 20
    ws.freeze_panes = "A2"

    filename = f"jamestown_hearings_{date.today()}.xlsx"
    wb.save(filename)
    print(f"\n  Exported to {filename}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n+========================================================================+")
    print("|        JAMESTOWN FOUNDATION -- CONGRESSIONAL HEARING TRACKER          |")
    print("+========================================================================+")

    if not HAS_FEEDPARSER:
        print("\n  NOTE: feedparser not installed -- using fallback XML parser.")
        print("        For better results: pip install feedparser\n")

    hearings = load_data()
    feeds    = load_feeds()

    # Auto-pull on first run
    if all(not f.get("last_fetched") for f in feeds):
        print("\n  First run -- pulling RSS feeds automatically...")
        new_items = pull_rss_feeds(hearings, feeds)
        print(f"  {len(new_items)} hearing(s) imported.\n")

    while True:
        total     = len(hearings)
        upcoming  = sum(1 for h in hearings
                        if h.get("status") in ("Upcoming", None)
                        and date.fromisoformat(h["date"]) >= date.today())
        rss_count = sum(1 for h in hearings if h.get("source") == "rss")

        print(f"\n  Tracked: {total}  |  Upcoming: {upcoming}  |  From RSS: {rss_count}  |  {date.today()}")
        divider()
        print("   1. Pull RSS feeds now")
        print("   2. Add hearing manually")
        print("   3. List all hearings")
        print("   4. Upcoming (next 14 days)")
        print("   5. View hearing details")
        print("   6. Edit hearing")
        print("   7. Delete hearing")
        print("   8. Search hearings")
        print("   9. Filter by status")
        print("  10. Manage RSS feeds")
        print("  11. Export to Excel")
        print("   0. Quit")
        divider()

        choice = input("  Select: ").strip()

        if choice == "1":
            print()
            new_items = pull_rss_feeds(hearings, feeds)
            print(f"\n  Done. {len(new_items)} new hearing(s) added.")
        elif choice == "2":
            add_hearing(hearings)
        elif choice == "3":
            list_hearings(hearings)
        elif choice == "4":
            upcoming_summary(hearings)
        elif choice == "5":
            view_hearing(hearings)
        elif choice == "6":
            edit_hearing(hearings)
        elif choice == "7":
            delete_hearing(hearings)
        elif choice == "8":
            search_hearings(hearings)
        elif choice == "9":
            status = pick("Filter by status:", STATUS_OPTIONS)
            list_hearings(hearings, filter_status=status)
        elif choice == "10":
            manage_feeds(hearings, feeds)
        elif choice == "11":
            export_to_excel(hearings)
        elif choice == "0":
            print("\n  Goodbye.\n")
            sys.exit(0)
        else:
            print("  Invalid choice.")

# ── DC Location / Heatmap helpers ─────────────────────────────────────────────

# Known Capitol Hill building coordinates (lat, lng)
DC_BUILDINGS = {
    # Senate side
    "russell":  (38.8928, -77.0073),
    "dirksen":  (38.8924, -77.0064),
    "hart":     (38.8921, -77.0058),
    "capitol":  (38.8899, -77.0091),
    # House side
    "cannon":   (38.8872, -77.0076),
    "longworth":(38.8863, -77.0086),
    "rayburn":  (38.8851, -77.0096),
    # Other
    "ford":     (38.8878, -77.0058),   # Ford House Office Building
    "o'neill":  (38.8875, -77.0062),   # Thomas P. O'Neill Jr. Federal Building
    "cvc":      (38.8895, -77.0083),   # Capitol Visitor Center
}

# Keyword → building key (checked in order against notes/topic, case-insensitive)
_BUILDING_KEYWORDS = [
    ("russell",   "russell"),
    ("dirksen",   "dirksen"),
    ("hart",      "hart"),
    ("cannon",    "cannon"),
    ("longworth", "longworth"),
    ("rayburn",   "rayburn"),
    ("ford",      "ford"),
    ("o'neill",   "o'neill"),
    ("capitol visitor", "cvc"),
    ("webex",     None),  # virtual — skip
]

# Committee → default building when no explicit location is found
_COMMITTEE_DEFAULT_BUILDING = {
    "Senate Armed Services (SASC)":       "russell",
    "Senate Foreign Relations (SFRC)":    "dirksen",
    "Senate Intelligence (SSCI)":         "hart",
    "Senate Homeland Security (SHSGAC)":  "dirksen",
    "House Armed Services (HASC)":        "rayburn",
    "House Foreign Affairs (HFAC)":       "longworth",
    "House Intelligence (HPSCI)":         "cvc",
    "House Homeland Security (HHSC)":     "cannon",
}

def resolve_hearing_location(h):
    """
    Return (lat, lng, building_label) for a hearing dict, or None if unknown.
    Checks the 'notes' field first (Congress.gov API populates room/building),
    then falls back to the committee's primary building.
    """
    text = (h.get("notes") or "").lower()

    for keyword, bkey in _BUILDING_KEYWORDS:
        if keyword in text:
            if bkey is None:
                return None   # virtual meeting
            coords = DC_BUILDINGS.get(bkey)
            if coords:
                label = keyword.title() + " Building"
                return (*coords, label)

    # Fall back to committee default
    bkey = _COMMITTEE_DEFAULT_BUILDING.get(h.get("committee", ""))
    if bkey:
        coords = DC_BUILDINGS[bkey]
        return (*coords, bkey.title() + " (default)")

    return None

def build_heatmap_points(hearings):
    """
    Return a list of dicts suitable for JSON serialisation and Leaflet.heat.
    Each point: {lat, lng, weight, label, committee, topic, date, url}
    Weight is boosted for action-required / upcoming hearings.
    """
    points = []
    for h in hearings:
        loc = resolve_hearing_location(h)
        if not loc:
            continue
        lat, lng, building = loc

        # Weight: upcoming + action-required hearings stand out more
        weight = 0.4
        if h.get("status") == "Upcoming":
            weight = 0.7
        if h.get("action") in ("Send brief", "Send questions",
                               "Offer testimony", "Request meeting"):
            weight = 1.0

        points.append({
            "lat":       lat,
            "lng":       lng,
            "weight":    weight,
            "building":  building,
            "committee": h.get("committee", ""),
            "topic":     h.get("topic", ""),
            "date":      h.get("date", ""),
            "status":    h.get("status", ""),
            "url":       h.get("url", ""),
            "id":        h.get("id"),
        })
    return points

if __name__ == "__main__":
    main()

