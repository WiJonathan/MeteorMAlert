import streamlit as st
import datetime
import math
import pandas as pd
import pytz
import requests
from skyfield.api import Topos, load, EarthSatellite

# --- 1. SETTINGS ---
st.set_page_config(page_title="Meteor-M TLE Predictor", page_icon="🛰️", layout="wide")

# Satellite NORAD IDs — fetch each by ID for reliability
TARGET_SATS = {
    57166: "Meteor M2-3",
    59051: "Meteor M2-4",
}

def tle_url(norad_id: int) -> str:
    return f"https://celestrak.org/NORAD/elements/gp.php?CATNR={norad_id}&FORMAT=tle"

# --- 2. SIDEBAR ---
with st.sidebar.form("location_form"):
    st.header("📍 Location & Settings")
    new_lat = st.number_input("Latitude", value=52.10, format="%.4f")
    new_lng = st.number_input("Longitude", value=6.45, format="%.4f")
    new_alt = st.number_input("Altitude (m)", value=18)

    all_tz = pytz.all_timezones
    default_tz_idx = all_tz.index("Europe/Amsterdam") if "Europe/Amsterdam" in all_tz else 0
    new_tz = st.selectbox("Local Timezone", all_tz, index=default_tz_idx)

    new_el = st.slider("Min Elevation (°)", 10, 90, 40)
    new_days = st.slider("Prediction Window (Days)", 1, 10, 5)
    show_night = st.checkbox("Show Night passes", value=False)

    submitted = st.form_submit_button("Apply")

LAT = new_lat
LNG = new_lng
ALT = new_alt
LOCAL_TZ = pytz.timezone(new_tz)
MIN_EL = new_el
DAYS = new_days

# --- 3. HELPER FUNCTIONS ---

ts = load.timescale(builtin=True)  # Never downloads anything — precision fine for pass prediction

@st.cache_data(ttl=43200)  # Cache TLE data for 12 hours
def fetch_tles(norad_ids: tuple):
    """Fetch TLEs in-memory via requests — no disk I/O, fast."""
    sats = []
    for norad_id in norad_ids:
        try:
            r = requests.get(tle_url(norad_id), timeout=10)
            r.raise_for_status()
            lines = [l.strip() for l in r.text.strip().splitlines() if l.strip()]
            if len(lines) < 3:
                st.warning(f"⚠️ Unexpected TLE format for NORAD ID {norad_id}")
                continue
            # lines[0] = name, lines[1] = TLE line 1, lines[2] = TLE line 2
            sat = EarthSatellite(lines[1], lines[2], TARGET_SATS[norad_id], ts)
            sats.append(sat)
        except Exception as e:
            st.warning(f"⚠️ Failed to load TLE for NORAD ID {norad_id}: {e}")
    return sats

def get_compass_dir(azimuth: float) -> str:
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[int((azimuth + 11.25) / 22.5) % 16]

def sun_elevation_deg(dt_utc: datetime.datetime, lat_deg: float, lng_deg: float) -> float:
    """
    Pure-math solar elevation — no ephemeris file needed.
    Accurate to ~±0.5° which is plenty for a daytime/night check.
    """
    # Day of year
    n = dt_utc.timetuple().tm_yday
    # Solar declination (degrees)
    decl = 23.45 * math.sin(math.radians((360 / 365) * (n - 81)))
    # Equation of time (minutes)
    B = math.radians((360 / 365) * (n - 81))
    eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)
    # Solar noon correction
    solar_time = (dt_utc.hour * 60 + dt_utc.minute + dt_utc.second / 60
                  + lng_deg * 4 + eot)
    hour_angle = (solar_time / 4) - 180  # degrees
    # Solar elevation
    lat_r = math.radians(lat_deg)
    decl_r = math.radians(decl)
    ha_r = math.radians(hour_angle)
    sin_el = (math.sin(lat_r) * math.sin(decl_r)
              + math.cos(lat_r) * math.cos(decl_r) * math.cos(ha_r))
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_el))))

def is_daytime(t, lat: float, lng: float, horizon_deg: float = -6.0) -> bool:
    """True if sun is above horizon_deg (civil twilight by default)."""
    dt_utc = t.utc_datetime()
    return sun_elevation_deg(dt_utc, lat, lng) > horizon_deg

# --- 4. MAIN CALCULATION ---
st.title("🛰️ Meteor-M Pass Predictor")

observer_topos = Topos(latitude_degrees=LAT, longitude_degrees=LNG, elevation_m=ALT)

tles = fetch_tles(tuple(TARGET_SATS.keys()))

if not tles:
    st.error("❌ Could not load any satellite TLEs. Check your internet connection or try again later.")
    st.stop()

now = datetime.datetime.now(pytz.utc)
t0 = ts.from_datetime(now)
t1 = ts.from_datetime(now + datetime.timedelta(days=DAYS))

all_data = []
rejected_passes = []

with st.spinner("Calculating passes..."):
    for sat in tles:
        try:
            times, events = sat.find_events(observer_topos, t0, t1, altitude_degrees=MIN_EL)
        except Exception as e:
            st.warning(f"⚠️ Error computing passes for {sat.name}: {e}")
            continue

        i = 0
        while i < len(events):
            # Find clean Rise(0) → Peak(1) → Set(2) triplets
            if (
                events[i] == 0
                and i + 2 < len(events)
                and events[i + 1] == 1
                and events[i + 2] == 2
            ):
                t_rise, t_peak, t_set = times[i], times[i + 1], times[i + 2]

                # Pure-math daytime check — no ephemeris file needed
                daytime = is_daytime(t_rise, LAT, LNG)

                if show_night or daytime:
                    diff_rise = (sat - observer_topos).at(t_rise)
                    diff_peak = (sat - observer_topos).at(t_peak)
                    diff_set = (sat - observer_topos).at(t_set)

                    el_peak, az_peak, _ = diff_peak.altaz()
                    _, az_rise, _ = diff_rise.altaz()
                    _, az_set, _ = diff_set.altaz()

                    duration_s = (t_set - t_rise) * 24 * 3600  # days → seconds

                    local_time = t_rise.astimezone(LOCAL_TZ).strftime("%d %b, %H:%M")

                    all_data.append({
                        "Satellite": sat.name,
                        "Local Time": local_time,
                        "Max El": f"{int(el_peak.degrees)}°",
                        "Peak Direction": get_compass_dir(az_peak.degrees),
                        "Path": f"{get_compass_dir(az_rise.degrees)} ➔ {get_compass_dir(az_set.degrees)}",
                        "Duration": f"{int(duration_s // 60)}m {int(duration_s % 60)}s",
                        "RawTime": t_rise.tt,
                    })
                else:
                    rejected_passes.append(
                        f"❌ {sat.name} at "
                        f"{t_rise.astimezone(LOCAL_TZ).strftime('%d %b %H:%M')} — Night pass"
                    )
                i += 3  # Skip past the full triplet
            else:
                i += 1  # Edge case: malformed event sequence, step forward

# --- 5. DISPLAY ---
if all_data:
    df = pd.DataFrame(all_data).sort_values("RawTime").reset_index(drop=True)
    next_pass = df.iloc[0]

    st.success(f"🎯 **Next pass:** {next_pass['Satellite']} — {next_pass['Local Time']}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Max Elevation", next_pass["Max El"])
    c2.metric("Peak Direction", next_pass["Peak Direction"])
    c3.metric("Duration", next_pass["Duration"])
    c4.metric("Path", next_pass["Path"])

    st.divider()
    st.subheader(f"All passes — next {DAYS} day(s)")
    st.dataframe(
        df.drop(columns=["RawTime"]),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.warning("No eligible passes found in the selected window. Try lowering min elevation or enabling night passes.")

with st.expander(f"Rejected passes ({len(rejected_passes)})"):
    if rejected_passes:
        for msg in rejected_passes:
            st.write(msg)
    else:
        st.write("None.")
