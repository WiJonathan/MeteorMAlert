import streamlit as st
import datetime
import json
import math
import pandas as pd
import pytz
import plotly.graph_objects as go
from pathlib import Path
from skyfield.api import Topos, load, EarthSatellite, wgs84

# --- 1. SETTINGS ---
st.set_page_config(page_title="Meteor-M TLE Predictor", page_icon="🛰️", layout="wide")

TLE_FILE = Path(__file__).parent / "tles.json"

# Meteor LRPT swath width ~2800 km
SWATH_KM = 2800

# --- 2. SIDEBAR ---
with st.sidebar.form("location_form"):
    st.header("📍 Location & Settings")
    new_lat = st.number_input("Latitude", value=52.10, format="%.4f")
    new_lng = st.number_input("Longitude", value=6.45, format="%.4f")
    new_alt = st.number_input("Altitude (m)", value=18)

    all_tz = pytz.all_timezones
    default_tz_idx = all_tz.index("Europe/Amsterdam") if "Europe/Amsterdam" in all_tz else 0
    new_tz = st.selectbox("Local Timezone", all_tz, index=default_tz_idx)

    new_el = st.slider("Min Elevation (°)", 0, 90, 10)
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

ts = load.timescale(builtin=True)

@st.cache_data(ttl=3600)
def load_tle_strings():
    if not TLE_FILE.exists():
        return None, None
    with open(TLE_FILE) as f:
        data = json.load(f)
    return list(data["satellites"].values()), data["fetched_at"]

def load_tles_from_file():
    records, fetched_at = load_tle_strings()
    if not records:
        return None, None
    sats = [EarthSatellite(r["tle_line1"], r["tle_line2"], r["name"], ts) for r in records]
    return sats, fetched_at

def get_compass_dir(azimuth: float) -> str:
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[int((azimuth + 11.25) / 22.5) % 16]

def sun_elevation_deg(dt_utc, lat_deg, lng_deg):
    n = dt_utc.timetuple().tm_yday
    decl = 23.45 * math.sin(math.radians((360 / 365) * (n - 81)))
    B = math.radians((360 / 365) * (n - 81))
    eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)
    solar_time = dt_utc.hour * 60 + dt_utc.minute + dt_utc.second / 60 + lng_deg * 4 + eot
    hour_angle = (solar_time / 4) - 180
    lat_r, decl_r, ha_r = math.radians(lat_deg), math.radians(decl), math.radians(hour_angle)
    sin_el = math.sin(lat_r) * math.sin(decl_r) + math.cos(lat_r) * math.cos(decl_r) * math.cos(ha_r)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_el))))

def is_daytime(t, lat, lng, horizon_deg=-6.0):
    return sun_elevation_deg(t.utc_datetime(), lat, lng) > horizon_deg

def offset_latlon(lat, lon, bearing_deg, distance_km):
    """Offset a lat/lon by distance_km in bearing_deg direction."""
    R = 6371.0
    d = distance_km / R
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    b_r = math.radians(bearing_deg)
    lat2 = math.asin(math.sin(lat_r) * math.cos(d) +
                     math.cos(lat_r) * math.sin(d) * math.cos(b_r))
    lon2 = lon_r + math.atan2(math.sin(b_r) * math.sin(d) * math.cos(lat_r),
                               math.cos(d) - math.sin(lat_r) * math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)

def compute_pass_timeline(sat, observer_topos, t_rise, t_set):
    """Compute az/el/lat/lon at 30-second intervals through a pass."""
    duration_s = (t_set - t_rise) * 24 * 3600
    steps = max(2, int(duration_s / 30))
    times = [t_rise + (i / steps) * (t_set - t_rise) for i in range(steps + 1)]
    rows = []
    for t in times:
        diff = (sat - observer_topos).at(t)
        el, az, _ = diff.altaz()
        geo = wgs84.subpoint_of(sat.at(t))
        rows.append({
            "t": t,
            "el": el.degrees,
            "az": az.degrees,
            "lat": geo.latitude.degrees,
            "lon": geo.longitude.degrees,
            "label": t.astimezone(LOCAL_TZ).strftime("%H:%M:%S"),
        })
    return rows

def make_sky_plot(timeline, sat_name):
    """Polar sky plot — azimuth around, elevation from edge (0°) to center (90°)."""
    els = [90 - r["el"] for r in timeline]  # invert so 90° is center
    azs = [r["az"] for r in timeline]
    labels = [r["label"] for r in timeline]

    # Mark minute ticks
    minute_els, minute_azs, minute_labels = [], [], []
    last_min = None
    for r in timeline:
        dt = r["t"].astimezone(LOCAL_TZ)
        if dt.second < 30 and last_min != dt.minute:
            minute_els.append(90 - r["el"])
            minute_azs.append(r["az"])
            minute_labels.append(r["label"])
            last_min = dt.minute

    fig = go.Figure()

    # Pass arc
    fig.add_trace(go.Scatterpolar(
        r=els, theta=azs, mode="lines",
        line=dict(color="#00aaff", width=3),
        name=sat_name, hovertext=labels, hoverinfo="text"
    ))

    # Rise marker
    fig.add_trace(go.Scatterpolar(
        r=[els[0]], theta=[azs[0]], mode="markers+text",
        marker=dict(color="lime", size=12, symbol="circle"),
        text=["AOS"], textposition="top center",
        name="AOS", hoverinfo="skip"
    ))

    # Set marker
    fig.add_trace(go.Scatterpolar(
        r=[els[-1]], theta=[azs[-1]], mode="markers+text",
        marker=dict(color="red", size=12, symbol="circle"),
        text=["LOS"], textposition="top center",
        name="LOS", hoverinfo="skip"
    ))

    # Minute markers
    fig.add_trace(go.Scatterpolar(
        r=minute_els, theta=minute_azs, mode="markers+text",
        marker=dict(color="yellow", size=8, symbol="circle"),
        text=minute_labels, textposition="top right",
        textfont=dict(size=9), name="Minutes", hoverinfo="skip"
    ))

    # Peak marker
    peak_idx = min(range(len(els)), key=lambda i: els[i])
    fig.add_trace(go.Scatterpolar(
        r=[els[peak_idx]], theta=[azs[peak_idx]], mode="markers+text",
        marker=dict(color="orange", size=14, symbol="star"),
        text=[f"MAX {int(timeline[peak_idx]['el'])}°"],
        textposition="top center",
        name="Peak", hoverinfo="skip"
    ))

    fig.update_layout(
        polar=dict(
            angularaxis=dict(direction="clockwise", rotation=90,
                             tickvals=[0,45,90,135,180,225,270,315],
                             ticktext=["N","NE","E","SE","S","SW","W","NW"]),
            radialaxis=dict(range=[90, 0], tickvals=[0,30,60,90],
                            ticktext=["90°","60°","30°","0°"],
                            showgrid=True, gridcolor="rgba(255,255,255,0.2)"),
            bgcolor="rgba(0,10,30,0.95)",
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        margin=dict(l=40, r=40, t=40, b=40),
        height=420,
    )
    return fig

def make_ground_track(timeline, sat_name, observer_lat, observer_lon):
    """Ground track map over Europe with swath width and minute markers."""
    lats = [r["lat"] for r in timeline]
    lons = [r["lon"] for r in timeline]
    labels = [r["label"] for r in timeline]

    # Build swath edge lines
    half_swath = SWATH_KM / 2
    left_lats, left_lons, right_lats, right_lons = [], [], [], []

    for i in range(len(timeline)):
        # Flight direction from adjacent points
        if i < len(timeline) - 1:
            dlat = timeline[i+1]["lat"] - timeline[i]["lat"]
            dlon = timeline[i+1]["lon"] - timeline[i]["lon"]
        else:
            dlat = timeline[i]["lat"] - timeline[i-1]["lat"]
            dlon = timeline[i]["lon"] - timeline[i-1]["lon"]
        bearing = math.degrees(math.atan2(dlon, dlat)) % 360
        ll = offset_latlon(lats[i], lons[i], (bearing - 90) % 360, half_swath)
        rl = offset_latlon(lats[i], lons[i], (bearing + 90) % 360, half_swath)
        left_lats.append(ll[0]); left_lons.append(ll[1])
        right_lats.append(rl[0]); right_lons.append(rl[1])

    # Minute markers
    min_lats, min_lons, min_labels = [], [], []
    last_min = None
    for r in timeline:
        dt = r["t"].astimezone(LOCAL_TZ)
        if dt.second < 30 and last_min != dt.minute:
            min_lats.append(r["lat"]); min_lons.append(r["lon"])
            min_labels.append(r["label"])
            last_min = dt.minute

    fig = go.Figure()

    # Swath fill
    swath_lats = left_lats + list(reversed(right_lats)) + [left_lats[0]]
    swath_lons = left_lons + list(reversed(right_lons)) + [left_lons[0]]
    fig.add_trace(go.Scattergeo(
        lat=swath_lats, lon=swath_lons, mode="lines",
        fill="toself", fillcolor="rgba(0,170,255,0.15)",
        line=dict(color="rgba(0,170,255,0.4)", width=1),
        name="Swath", hoverinfo="skip"
    ))

    # Ground track line
    fig.add_trace(go.Scattergeo(
        lat=lats, lon=lons, mode="lines",
        line=dict(color="#00aaff", width=2.5),
        name=sat_name, hovertext=labels, hoverinfo="text"
    ))

    # Minute markers
    fig.add_trace(go.Scattergeo(
        lat=min_lats, lon=min_lons, mode="markers+text",
        marker=dict(color="yellow", size=7),
        text=min_labels, textposition="top right",
        textfont=dict(size=9, color="yellow"),
        name="Minutes", hoverinfo="skip"
    ))

    # AOS / LOS
    fig.add_trace(go.Scattergeo(
        lat=[lats[0], lats[-1]], lon=[lons[0], lons[-1]],
        mode="markers+text",
        marker=dict(color=["lime", "red"], size=12),
        text=["AOS", "LOS"], textposition="top center",
        textfont=dict(color="white"), name="AOS/LOS", hoverinfo="skip"
    ))

    # Observer location
    fig.add_trace(go.Scattergeo(
        lat=[observer_lat], lon=[observer_lon],
        mode="markers+text",
        marker=dict(color="orange", size=10, symbol="star"),
        text=["You"], textposition="top right",
        textfont=dict(color="orange"), name="Observer", hoverinfo="skip"
    ))

    fig.update_geos(
        scope="europe",
        projection_type="natural earth",
        showland=True, landcolor="rgb(40,60,40)",
        showocean=True, oceancolor="rgb(10,20,50)",
        showcoastlines=True, coastlinecolor="rgba(255,255,255,0.4)",
        showborders=True, bordercolor="rgba(255,255,255,0.2)",
        showcountries=True, countrycolor="rgba(255,255,255,0.15)",
        bgcolor="rgba(0,0,0,0)",
        lataxis_range=[20, 80], lonaxis_range=[-30, 50],
    )

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
        height=420,
    )
    return fig

# --- 4. MAIN ---
st.title("🛰️ Meteor-M Pass Predictor")

tles, fetched_at = load_tles_from_file()

if not tles:
    st.error(
        "❌ `tles.json` not found. "
        "Run `fetch_tles.py` locally once to generate it, then commit it to your repo."
    )
    st.stop()

with st.sidebar:
    try:
        age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(fetched_at)
        hours_ago = int(age.total_seconds() // 3600)
        st.caption(f"🕐 TLE data: {hours_ago}h ago")
    except Exception:
        st.caption(f"🕐 TLE fetched at: {fetched_at}")

observer_topos = Topos(latitude_degrees=LAT, longitude_degrees=LNG, elevation_m=ALT)

now = datetime.datetime.now(pytz.utc)
t0 = ts.from_datetime(now)
t1 = ts.from_datetime(now + datetime.timedelta(days=DAYS))

all_data = []
rejected_passes = []
pass_objects = []  # Store raw pass data for detail view

with st.spinner("Calculating passes..."):
    for sat in tles:
        try:
            times, events = sat.find_events(observer_topos, t0, t1, altitude_degrees=0)
        except Exception as e:
            st.warning(f"⚠️ Error computing passes for {sat.name}: {e}")
            continue

        i = 0
        while i < len(events):
            if (events[i] == 0 and i + 2 < len(events)
                    and events[i+1] == 1 and events[i+2] == 2):
                t_rise, t_peak, t_set = times[i], times[i+1], times[i+2]

                diff_peak_check = (sat - observer_topos).at(t_peak)
                el_check, _, _ = diff_peak_check.altaz()
                if el_check.degrees < MIN_EL:
                    i += 3
                    continue

                daytime = is_daytime(t_rise, LAT, LNG)

                if show_night or daytime:
                    diff_rise = (sat - observer_topos).at(t_rise)
                    diff_peak = (sat - observer_topos).at(t_peak)
                    diff_set  = (sat - observer_topos).at(t_set)

                    el_peak, az_peak, _ = diff_peak.altaz()
                    _, az_rise, _       = diff_rise.altaz()
                    _, az_set, _        = diff_set.altaz()

                    duration_s = (t_set - t_rise) * 24 * 3600
                    pass_id = len(all_data)

                    all_data.append({
                        "Satellite":      sat.name,
                        "Local Time":     t_rise.astimezone(LOCAL_TZ).strftime("%d %b, %H:%M"),
                        "Max El":         f"{int(el_peak.degrees)}°",
                        "Peak Direction": get_compass_dir(az_peak.degrees),
                        "Path":           f"{get_compass_dir(az_rise.degrees)} ➔ {get_compass_dir(az_set.degrees)}",
                        "Duration":       f"{int(duration_s // 60)}m {int(duration_s % 60)}s",
                        "RawTime":        t_rise.tt,
                    })
                    pass_objects.append({
                        "sat": sat,
                        "t_rise": t_rise,
                        "t_peak": t_peak,
                        "t_set": t_set,
                    })
                else:
                    rejected_passes.append(
                        f"❌ {sat.name} at "
                        f"{t_rise.astimezone(LOCAL_TZ).strftime('%d %b %H:%M')} — Night pass"
                    )
                i += 3
            else:
                i += 1

# --- 5. DISPLAY ---
if all_data:
    df = pd.DataFrame(all_data).sort_values("RawTime").reset_index(drop=True)
    # Keep sorted index aligned with pass_objects
    sorted_indices = list(pd.DataFrame(all_data).sort_values("RawTime").index)
    sorted_pass_objects = [pass_objects[i] for i in sorted_indices]

    next_pass = df.iloc[0]
    st.success(f"🎯 **Next pass:** {next_pass['Satellite']} — {next_pass['Local Time']}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Max Elevation",  next_pass["Max El"])
    c2.metric("Peak Direction", next_pass["Peak Direction"])
    c3.metric("Duration",       next_pass["Duration"])
    c4.metric("Path",           next_pass["Path"])

    st.divider()
    st.subheader(f"All passes — next {DAYS} day(s)")

    # Display table with detail buttons
    header_cols = st.columns([2, 2, 1, 1.5, 2, 1.5, 1])
    for col, label in zip(header_cols, ["Satellite", "Local Time", "Max El",
                                         "Peak Dir", "Path", "Duration", "Detail"]):
        col.markdown(f"**{label}**")

    st.divider()

    for idx, row in df.iterrows():
        cols = st.columns([2, 2, 1, 1.5, 2, 1.5, 1])
        cols[0].write(row["Satellite"])
        cols[1].write(row["Local Time"])
        cols[2].write(row["Max El"])
        cols[3].write(row["Peak Direction"])
        cols[4].write(row["Path"])
        cols[5].write(row["Duration"])
        if cols[6].button("🔍", key=f"detail_{idx}"):
            st.session_state["selected_pass"] = idx

    # --- 6. DETAIL VIEW ---
    if "selected_pass" in st.session_state:
        sel_idx = st.session_state["selected_pass"]
        if sel_idx < len(sorted_pass_objects):
            p = sorted_pass_objects[sel_idx]
            sat = p["sat"]
            t_rise, t_peak, t_set = p["t_rise"], p["t_peak"], p["t_set"]
            row = df.iloc[sel_idx]

            st.divider()
            st.subheader(f"📡 {row['Satellite']} — {row['Local Time']}")

            timeline = compute_pass_timeline(sat, observer_topos, t_rise, t_set)

            col_sky, col_map = st.columns(2)
            with col_sky:
                st.markdown("**🌐 Sky Plot**")
                st.plotly_chart(make_sky_plot(timeline, sat.name),
                                use_container_width=True, key="skyplot")
            with col_map:
                st.markdown("**🗺️ Ground Track**")
                st.plotly_chart(make_ground_track(timeline, sat.name, LAT, LNG),
                                use_container_width=True, key="groundtrack")

            # Minute-by-minute table
            st.markdown("**⏱️ Minute-by-minute tracking**")
            table_rows = []
            last_min = None
            for r in timeline:
                dt = r["t"].astimezone(LOCAL_TZ)
                if dt.second < 15 and last_min != dt.minute:
                    table_rows.append({
                        "Time":      r["label"],
                        "Elevation": f"{r['el']:.1f}°",
                        "Azimuth":   f"{r['az']:.1f}°",
                        "Direction": get_compass_dir(r["az"]),
                    })
                    last_min = dt.minute

            st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

            if st.button("✖ Close detail"):
                del st.session_state["selected_pass"]
                st.rerun()

else:
    st.warning("No eligible passes found. Try lowering min elevation or enabling night passes.")

with st.expander(f"Rejected passes ({len(rejected_passes)})"):
    for msg in rejected_passes:
        st.write(msg)
    if not rejected_passes:
        st.write("None.")
