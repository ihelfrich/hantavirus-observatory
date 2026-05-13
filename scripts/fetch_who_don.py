#!/usr/bin/env python3
"""Fetch WHO Disease Outbreak News API → who_don.json (same-origin cache)."""
import json, re, ssl, sys, urllib.request
from datetime import datetime, timezone

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()

HEADERS = {
    "User-Agent": "HantavirusObservatory/1.0 (+https://ihelfrich.github.io/hantavirus-observatory/)",
    "Accept": "application/json",
}

def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.read().decode("utf-8", errors="replace")

def parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s.split("+")[0].strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None

def strip_html(s):
    return re.sub(r"<[^>]+>", " ", s or "").strip()

def main():
    url = "https://www.who.int/api/news/diseaseoutbreaknews"
    out = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "source": "WHO Disease Outbreak News API",
           "count": 0, "items": []}

    try:
        raw = fetch(url)
        d = json.loads(raw)
    except Exception as e:
        print(f"WHO DON fetch failed: {e}", file=sys.stderr)
        with open("who_don.json", "w") as f:
            json.dump(out, f, indent=2)
        return

    items = []
    for v in (d.get("value") or []):
        title = (v.get("Title") or "").strip()
        if not title:
            continue
        pub = parse_dt(v.get("PublicationDateAndTime", ""))
        item_url_path = v.get("ItemDefaultUrl") or v.get("UrlName") or ""
        if item_url_path and not item_url_path.startswith("http"):
            full_url = "https://www.who.int" + item_url_path
        else:
            full_url = item_url_path
        summary = strip_html(v.get("Summary") or v.get("OverrideDownloadDateText") or "")
        items.append({
            "date":  pub.strftime("%Y-%m-%d") if pub else "",
            "ts":    pub.isoformat() if pub else "",
            "title": title[:280],
            "url":   full_url,
            "summary": summary[:400],
        })

    items.sort(key=lambda x: x.get("ts", ""), reverse=True)
    out["items"] = items[:60]
    out["count"] = len(out["items"])

    # Tag any hantavirus / hemorrhagic-fever-with-renal-syndrome / HPS items
    hanta_pat = re.compile(r"hanta|HFRS|HPS|sin nombre|puumala|andes virus", re.I)
    for it in out["items"]:
        if hanta_pat.search(it["title"]) or hanta_pat.search(it.get("summary","")):
            it["hantavirus_match"] = True

    with open("who_don.json", "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"WHO DON: {out['count']} items, "
          f"{sum(1 for i in out['items'] if i.get('hantavirus_match'))} hantavirus-flagged")

if __name__ == "__main__":
    main()
