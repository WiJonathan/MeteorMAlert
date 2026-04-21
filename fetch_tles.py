"""
fetch_tles.py — run by GitHub Actions every 12 hours.
Fetches GP data in JSON format (future-proof, no 5-digit NORAD limit)
and writes tles.json for the Streamlit app to consume.
"""

import json
import datetime
import requests

TARGET_SATS = {
    57166: "Meteor M2-3",
    59051: "Meteor M2-4",
    38771: "MetOp-B",
    43689: "MetOp-C",
}

# CelesTrak TLE format — plain text, 3 lines per satellite
def gp_url(norad_id: int) -> str:
    return f"https://celestrak.org/NORAD/elements/gp.php?CATNR={norad_id}&FORMAT=tle"

def fetch():
    results = {}
    for norad_id, name in TARGET_SATS.items():
        r = requests.get(gp_url(norad_id), timeout=15)
        r.raise_for_status()
        lines = [l.strip() for l in r.text.strip().splitlines() if l.strip()]
        if len(lines) < 3:
            raise ValueError(f"Unexpected TLE response for NORAD {norad_id}: {r.text!r}")
        results[str(norad_id)] = {
            "name": name,
            "tle_line1": lines[1],
            "tle_line2": lines[2],
        }
        print(f"✅ Fetched {name} (NORAD {norad_id})")

    output = {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "satellites": results,
    }

    with open("tles.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ tles.json written with {len(results)} satellites.")

if __name__ == "__main__":
    fetch()
