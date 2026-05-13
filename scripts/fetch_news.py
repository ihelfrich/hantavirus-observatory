#!/usr/bin/env python3
"""
Fetch hantavirus / outbreak news from sources that DON'T have browser CORS,
parse server-side, write news.json that the SPA reads same-origin.

Sources:
  - CIDRAP RSS (Center for Infectious Disease Research and Policy)
  - OutbreakNewsToday hantavirus + infectious-disease category feeds
  - GDELT 2.0 Doc API (rate-limited: one request every 5s; we make 1)
"""

import json
import time
import re
import ssl
import sys
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()

HEADERS = {
    "User-Agent": "HantavirusObservatory/1.0 (+https://ihelfrich.github.io/hantavirus-observatory/)",
    "Accept": "application/rss+xml, application/xml, application/json, text/xml, */*",
}

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.read().decode("utf-8", errors="replace")

def parse_rfc822(s):
    if not s:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S GMT",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(s.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None

def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()

def parse_rss(xml_text, source_name, location="", max_items=25):
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  [{source_name}] parse error: {e}", file=sys.stderr)
        return items

    # RSS 2.0
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub  = parse_rfc822(it.findtext("pubDate") or "")
        if not title:
            continue
        items.append({
            "time": pub.strftime("%H:%M") if pub else "—",
            "date": pub.strftime("%Y-%m-%d") if pub else "",
            "ts":   pub.isoformat() if pub else "",
            "src":  source_name,
            "head": strip_html(title)[:280],
            "url":  link,
            "loc":  location,
            "lang": "en",
            "tags": [source_name],
            "live": True,
        })
        if len(items) >= max_items:
            break

    # Atom fallback
    if not items:
        ns = "{http://www.w3.org/2005/Atom}"
        for it in root.iter(ns + "entry"):
            title = (it.findtext(ns + "title") or "").strip()
            link_el = it.find(ns + "link")
            link = link_el.get("href", "") if link_el is not None else ""
            pub  = parse_rfc822(it.findtext(ns + "updated") or it.findtext(ns + "published") or "")
            if not title:
                continue
            items.append({
                "time": pub.strftime("%H:%M") if pub else "—",
                "date": pub.strftime("%Y-%m-%d") if pub else "",
                "ts":   pub.isoformat() if pub else "",
                "src":  source_name,
                "head": strip_html(title)[:280],
                "url":  link,
                "loc":  location,
                "lang": "en",
                "tags": [source_name],
                "live": True,
            })
            if len(items) >= max_items:
                break

    print(f"  [{source_name}] {len(items)} items")
    return items

def fetch_gdelt(query="hantavirus", n=25):
    q = urllib.parse.quote(f'"{query}" (outbreak OR cases OR virus OR epidemic OR hemorrhagic OR rodent OR surveillance)')
    url = (f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}"
           f"&mode=artlist&maxrecords={n}&format=json&timespan=14days&sort=DateDesc")
    try:
        raw = fetch(url, timeout=20)
        # Empty result body sometimes; guard
        if not raw.strip():
            print("  [GDELT] empty body")
            return []
        d = json.loads(raw)
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"  [GDELT] fetch failed: {e}", file=sys.stderr)
        return []

    items = []
    for a in (d.get("articles") or []):
        dt = a.get("seendatetime", "")
        try:
            parsed = datetime.strptime(dt, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            parsed = None
        src = (a.get("domain") or "").replace("www.", "").split(".")[0]
        items.append({
            "time": parsed.strftime("%H:%M") if parsed else "—",
            "date": parsed.strftime("%Y-%m-%d") if parsed else "",
            "ts":   parsed.isoformat() if parsed else "",
            "src":  src.capitalize() or "GDELT",
            "head": (a.get("title") or "")[:280],
            "url":  a.get("url", ""),
            "loc":  a.get("sourcecountry", ""),
            "lang": a.get("language", "en"),
            "tags": [a.get("language", "en"), a.get("sourcecountry", "")],
            "live": True,
        })
    print(f"  [GDELT] {len(items)} items")
    return items

SOURCES = [
    ("CIDRAP",              "https://www.cidrap.umn.edu/rss.xml",                                 "Minnesota"),
    ("OutbreakNewsToday",   "https://outbreaknewstoday.com/feed/",                                "Global"),
    ("CDC EID",             "https://wwwnc.cdc.gov/eid/rss/ahead-of-print.xml",                   "Atlanta"),
]

def main():
    all_items = []

    for source_name, url, location in SOURCES:
        try:
            xml = fetch(url)
            all_items.extend(parse_rss(xml, source_name, location))
            time.sleep(1)
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            print(f"  [{source_name}] fetch failed: {e}", file=sys.stderr)

    # GDELT — respect their 5s rate limit
    time.sleep(5)
    all_items.extend(fetch_gdelt("hantavirus", 25))

    # Deduplicate by URL (or head if no url)
    seen = set()
    unique = []
    for item in all_items:
        key = item.get("url") or item.get("head", "")[:80]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    # Sort newest first by ts
    unique.sort(key=lambda x: x.get("ts", ""), reverse=True)

    # Filter for hantavirus-relevant items where possible
    hanta_pat = re.compile(r"hanta|HFRS|HPS|sin nombre|puumala|andes virus|seoul virus|hantaan|deer mouse", re.I)
    hanta_only = [i for i in unique if hanta_pat.search(i.get("head", ""))]
    # Keep hanta_only first, then the rest
    rest = [i for i in unique if not hanta_pat.search(i.get("head", ""))]
    final = (hanta_only + rest)[:80]

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": list(set(s[0] for s in SOURCES)) + ["GDELT"],
        "count": len(final),
        "items": final,
    }

    with open("news.json", "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWrote news.json: {len(final)} items "
          f"({len(hanta_only)} hantavirus-specific)")

if __name__ == "__main__":
    main()
