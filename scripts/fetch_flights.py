#!/usr/bin/env python3
"""Fetch OpenSky Network global state vectors → flights.json (same-origin cache).
   Server-side runs without the browser CORS issue OpenSky's anonymous endpoint imposes."""
import json, ssl, sys, urllib.request
from datetime import datetime, timezone

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = ssl.create_default_context()

HEADERS = {"User-Agent": "HantavirusObservatory/1.0 (+https://ihelfrich.github.io/hantavirus-observatory/)"}

def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.read().decode("utf-8", errors="replace")

# OpenSky state vector columns:
#  0 icao24      1 callsign       2 origin_country  3 time_position
#  4 last_contact 5 longitude     6 latitude        7 baro_altitude
#  8 on_ground   9 velocity      10 true_track     11 vertical_rate
# 12 sensors    13 geo_altitude  14 squawk         15 spi  16 position_source

def main():
    out = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "source": "OpenSky Network state vectors (anonymous, server-side)",
           "time": None, "count": 0, "states": []}

    # Anonymous endpoint with global bbox; OpenSky rate-limits aggressively, so
    # ask for a sensible bbox covering all populated continents.
    url = ("https://opensky-network.org/api/states/all?"
           "lamin=-60&lamax=75&lomin=-180&lomax=180")
    try:
        raw = fetch(url)
        d = json.loads(raw)
    except Exception as e:
        print(f"OpenSky fetch failed: {e}", file=sys.stderr)
        with open("flights.json", "w") as f:
            json.dump(out, f, indent=2)
        return

    out["time"] = d.get("time")
    states_in = d.get("states") or []
    states_out = []
    for s in states_in:
        if not s or len(s) < 11:
            continue
        if s[8]:  # on_ground
            continue
        lon, lat = s[5], s[6]
        if lon is None or lat is None:
            continue
        states_out.append({
            "icao24":    s[0],
            "callsign":  (s[1] or "").strip(),
            "country":   s[2],
            "lon":       lon,
            "lat":       lat,
            "alt":       s[7],
            "velocity":  s[9],
            "heading":   s[10],
        })

    # Cap at 3000 — file-size sanity. Sort by callsign for stability.
    states_out.sort(key=lambda x: (x["callsign"] or "z", x["icao24"]))
    out["states"] = states_out[:3000]
    out["count"] = len(out["states"])

    with open("flights.json", "w") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"OpenSky: {out['count']} airborne aircraft (from {len(states_in)} states)")

if __name__ == "__main__":
    main()
