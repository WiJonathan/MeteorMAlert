import json
from pathlib import Path
 
import streamlit as st
from skyfield.api import Topos, load, EarthSatellite
 
TLE_FILE = Path(__file__).parent / "tles.json"
 
ts = load.timescale(builtin=True)
 
 
@st.cache_data(ttl=3600)
def load_tle_strings() -> tuple[list[dict] | None, str | None]:
    """Load raw TLE records from tles.json. Cached for 1 hour."""
    if not TLE_FILE.exists():
        return None, None
    try:
        with open(TLE_FILE) as f:
            data = json.load(f)
    except (json.JSONDecodeError, KeyError) as e:
        st.error(f"Failed to parse TLE file: {e}")
        st.stop()
    return list(data["satellites"].values()), data["fetched_at"]
 
 
def load_satellites(selected_names: list[str]) -> tuple[list[EarthSatellite] | None, str | None]:
    """Build EarthSatellite objects for the selected satellite names."""
    records, fetched_at = load_tle_strings()
    if not records:
        return None, None
    sats = [
        EarthSatellite(r["tle_line1"], r["tle_line2"], r["name"], ts)
        for r in records
        if r["name"] in selected_names
    ]
    return sats, fetched_at
 
 
def get_available_satellite_names() -> list[str]:
    """Return all satellite names present in tles.json."""
    records, _ = load_tle_strings()
    return [r["name"] for r in records] if records else []
 
 
def get_compass_dir(azimuth: float) -> str:
    """Convert a numeric azimuth (degrees) to a 16-point compass label."""
    dirs = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    return dirs[int((azimuth + 11.25) / 22.5) % 16]
 
 
def make_observer(lat: float, lng: float, alt: float) -> Topos:
    """Create a Skyfield Topos observer from coordinates."""
    return Topos(latitude_degrees=lat, longitude_degrees=lng, elevation_m=alt)
