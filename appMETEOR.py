import streamlit as st
import datetime
import json
import math
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
from skyfield.api import Topos, load, EarthSatellite, wgs84

# --- 1. SETTINGS ---
st.set_page_config(page_title="Meteor-M TLE Predictor", page_icon="🛰️", layout="wide")

TLE_FILE = Path(__file__).parent / "tles.json"

# Meteor LRPT scan half-angle and altitude used in swath calculation
METEOR_SCAN_HALF_ANGLE = 55.4
METEOR_ALT_KM = 820.0

# --- 2. SIDEBAR ---
with st.sidebar.form("location_form"):
    st.header("📍 Location & Settings")
    new_lat = st.number_input("Latitude", value=52.10, format="%.4f")
    new_lng = st.number_input("Longitude", value=6.45, format="%.4f")
    new_alt = st.number_input("Altitude (m)", value=18)

    tz_options = [f"UTC{'+' if h >= 0 else ''}{h}" for h in range(-12, 15)]
    default_tz_idx = tz_options.index("UTC+2") if "UTC+2" in tz_options else 0
    new_tz = st.selectbox("Timezone", tz_options, index=default_tz_idx)

    new_el = st.slider("Min Elevation (°)", 0, 90, 10)
    new_days = st.slider("Prediction Window (Days)", 1, 10, 5)
    show_night = st.checkbox("Show Night passes", value=False)

    submitted = st.form_submit_button("Apply")

LAT = new_lat
LNG = new_lng
ALT = new_alt
tz_offset = int(new_tz.replace("UTC", "").replace("+", "") or "0")
LOCAL_TZ = datetime.timezone(datetime.timedelta(hours=tz_offset))
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
    """Compute az/el/lat/lon at 30-second intervals through the full pass AOS to LOS."""
    duration_s = (t_set - t_rise) * 24 * 3600
    steps = max(2, int(duration_s / 30))
    rows = []
    for i in range(steps + 1):
        frac = i / steps
        t = t_rise + frac * (t_set - t_rise)
        diff = (sat - observer_topos).at(t)
        el, az, _ = diff.altaz()
        geo = wgs84.subpoint_of(sat.at(t))
        rows.append({
            "t": t,
            "el": max(0.0, el.degrees),  # clamp to 0, never skip
            "az": az.degrees,
            "lat": geo.latitude.degrees,
            "lon": geo.longitude.degrees,
            "label": t.astimezone(LOCAL_TZ).strftime("%H:%M:%S"),
        })
    return rows

def make_sky_plot(timeline, sat_name):
    """
    Observer's sky view: N at top, E at right (as if lying on your back looking up).
    Elevation rings: 0° at edge, 90° at centre.
    Uses Cartesian x/y so we control the projection exactly.
    """
    def azel_to_xy(az_deg, el_deg):
        """Convert az/el to x,y with N up, E right, horizon at r=1."""
        r = 1.0 - (el_deg / 90.0)  # 0 at zenith, 1 at horizon
        az_r = math.radians(az_deg)
        x = r * math.sin(az_r)   # E is +x
        y = r * math.cos(az_r)   # N is +y
        return x, y

    xs, ys, labels = [], [], []
    for r in timeline:
        x, y = azel_to_xy(r["az"], r["el"])
        xs.append(x); ys.append(y); labels.append(r["label"])

    # Minute markers — skip above 60° elevation (spreads ugly near zenith)
    min_xs, min_ys, min_labels, min_positions = [], [], [], []
    last_min = None
    toggle = 0
    for r in timeline:
        dt = r["t"].astimezone(LOCAL_TZ)
        if dt.second < 30 and last_min != dt.minute and r["el"] < 60:
            x, y = azel_to_xy(r["az"], r["el"])
            min_xs.append(x); min_ys.append(y)
            min_labels.append(r["label"])
            min_positions.append("top right" if toggle % 2 == 0 else "top left")
            toggle += 1
            last_min = dt.minute

    peak_idx = max(range(len(timeline)), key=lambda i: timeline[i]["el"])
    px, py = azel_to_xy(timeline[peak_idx]["az"], timeline[peak_idx]["el"])

    fig = go.Figure()

    # Elevation rings
    for el_ring, label in [(0, "0°"), (30, "30°"), (60, "60°"), (90, "90°")]:
        r = 1.0 - el_ring / 90.0
        angles = [i * math.pi / 180 for i in range(361)]
        fig.add_trace(go.Scatter(
            x=[r * math.sin(a) for a in angles],
            y=[r * math.cos(a) for a in angles],
            mode="lines", line=dict(color="rgba(255,255,255,0.15)", width=1),
            hoverinfo="skip", showlegend=False
        ))
        if el_ring < 90:
            fig.add_annotation(x=0, y=-r, text=label,
                               font=dict(color="rgba(255,255,255,0.5)", size=9),
                               showarrow=False, yshift=-8)

    # Cardinal direction lines & labels
    for az_deg, label in [(0,"N"),(90,"E"),(180,"S"),(270,"W")]:
        az_r = math.radians(az_deg)
        fig.add_trace(go.Scatter(
            x=[0, math.sin(az_r)], y=[0, math.cos(az_r)],
            mode="lines", line=dict(color="rgba(255,255,255,0.2)", width=1),
            hoverinfo="skip", showlegend=False
        ))
        fig.add_annotation(x=1.08 * math.sin(az_r), y=1.08 * math.cos(az_r),
                           text=f"<b>{label}</b>",
                           font=dict(color="white", size=13),
                           showarrow=False)

    # Pass arc
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="lines",
        line=dict(color="#00aaff", width=3),
        hovertext=labels, hoverinfo="text", showlegend=False
    ))

    # AOS
    fig.add_trace(go.Scatter(
        x=[xs[0]], y=[ys[0]], mode="markers+text",
        marker=dict(color="lime", size=12),
        text=["AOS"], textposition="top center",
        hoverinfo="skip", showlegend=False
    ))

    # LOS
    fig.add_trace(go.Scatter(
        x=[xs[-1]], y=[ys[-1]], mode="markers+text",
        marker=dict(color="red", size=12),
        text=["LOS"], textposition="top center",
        hoverinfo="skip", showlegend=False
    ))

    # Peak
    fig.add_trace(go.Scatter(
        x=[px], y=[py], mode="markers+text",
        marker=dict(color="orange", size=14, symbol="star"),
        text=[f"MAX {int(timeline[peak_idx]['el'])}°"],
        textposition="top center",
        hoverinfo="skip", showlegend=False
    ))

    # Minute markers
    for i in range(len(min_xs)):
        fig.add_trace(go.Scatter(
            x=[min_xs[i]], y=[min_ys[i]], mode="markers+text",
            marker=dict(color="yellow", size=7),
            text=[min_labels[i]], textposition=min_positions[i],
            textfont=dict(size=9), hoverinfo="skip", showlegend=False
        ))

    fig.update_layout(
        xaxis=dict(range=[-1.2, 1.2], visible=False, scaleanchor="y"),
        yaxis=dict(range=[-1.2, 1.2], visible=False),
        plot_bgcolor="rgb(0,10,30)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=20, b=20),
        height=350,
    )
    return fig

def swath_edge(sat_lat, sat_lon, sat_alt_km, bearing_deg, scan_angle_deg):
    """
    Compute swath edge lat/lon using proper Earth geometry.
    scan_angle_deg: half-angle from nadir (±55.4° for Meteor LRPT).
    """
    R = 6371.0
    # Earth central angle from satellite nadir to swath edge
    rho = math.asin((R / (R + sat_alt_km)) * math.sin(math.radians(scan_angle_deg)))
    # Ground distance in km
    ground_dist_km = R * (math.radians(scan_angle_deg) - rho)
    return offset_latlon(sat_lat, sat_lon, bearing_deg, ground_dist_km)

def make_ground_track(timeline, sat_name, observer_lat, observer_lon):
    """Ground track map with correct swath overlay and minute markers."""
    lats = [r["lat"] for r in timeline]
    lons = [r["lon"] for r in timeline]
    labels = [r["label"] for r in timeline]

    # --- Swath edges using proper Earth geometry ---
    SCAN_HALF_ANGLE = 55.4
    SAT_ALT_KM = 820.0
    left_lats, left_lons = [], []
    right_lats, right_lons = [], []

    for i in range(len(timeline)):
        # Use wide window bearing to smooth direction changes at orbit apex
        i0 = max(0, i - 4)
        i1 = min(len(timeline) - 1, i + 4)
        dlat = timeline[i1]["lat"] - timeline[i0]["lat"]
        dlon = timeline[i1]["lon"] - timeline[i0]["lon"]
        # If dlat is near zero (apex), use local derivative instead
        if abs(dlat) < 0.01 and abs(dlon) < 0.01:
            i0 = max(0, i - 1)
            i1 = min(len(timeline) - 1, i + 1)
            dlat = timeline[i1]["lat"] - timeline[i0]["lat"]
            dlon = timeline[i1]["lon"] - timeline[i0]["lon"]
        bearing = math.degrees(math.atan2(dlon, dlat)) % 360

        ll = swath_edge(lats[i], lons[i], SAT_ALT_KM, (bearing - 90) % 360, SCAN_HALF_ANGLE)
        rl = swath_edge(lats[i], lons[i], SAT_ALT_KM, (bearing + 90) % 360, SCAN_HALF_ANGLE)
        left_lats.append(ll[0]);  left_lons.append(ll[1])
        right_lats.append(rl[0]); right_lons.append(rl[1])

    # Polygon: left edge forward + right edge reversed = closed wedge
    poly_lats = left_lats + list(reversed(right_lats)) + [left_lats[0]]
    poly_lons = left_lons + list(reversed(right_lons)) + [left_lons[0]]

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
    fig.add_trace(go.Scattergeo(
        lat=poly_lats, lon=poly_lons, mode="lines",
        fill="toself", fillcolor="rgba(0,170,255,0.12)",
        line=dict(color="rgba(0,170,255,0.5)", width=1),
        hoverinfo="skip", showlegend=False
    ))

    # Ground track
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
        textfont=dict(color="white"), hoverinfo="skip"
    ))

    # Observer
    fig.add_trace(go.Scattergeo(
        lat=[observer_lat], lon=[observer_lon],
        mode="markers+text",
        marker=dict(color="orange", size=10, symbol="star"),
        text=["You"], textposition="top right",
        textfont=dict(color="orange"), hoverinfo="skip"
    ))

    fig.update_geos(
        projection_type="mercator",
        showland=True, landcolor="rgb(40,60,40)",
        showocean=True, oceancolor="rgb(10,20,50)",
        showcoastlines=True, coastlinecolor="rgba(255,255,255,0.4)",
        showcountries=True, countrycolor="rgba(255,255,255,0.3)",
        bgcolor="rgba(0,0,0,0)",
        fitbounds="locations",
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=20, b=20),
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

now = datetime.datetime.now(datetime.timezone.utc)
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
    st.caption("Click a row to see the sky plot and ground track.")

    display_df = df.drop(columns=["RawTime"]).copy()
    selection = st.dataframe(
        display_df,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
    )

    selected_rows = selection.selection.rows
    if selected_rows:
        st.session_state["selected_pass"] = selected_rows[0]

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

            # Minute-by-minute table — strictly every 60s from AOS, no wall-clock alignment
            st.markdown("**⏱️ Minute-by-minute tracking**")
            duration_s = (t_set - t_rise) * 24 * 3600
            table_rows = []
            sec = 0
            while sec <= duration_s:
                frac = sec / duration_s
                t_sample = t_rise + frac * (t_set - t_rise)
                diff = (sat - observer_topos).at(t_sample)
                el, az, _ = diff.altaz()
                table_rows.append({
                    "Time":      t_sample.astimezone(LOCAL_TZ).strftime("%H:%M:%S"),
                    "Elevation": f"{max(0.0, el.degrees):.1f}°",
                    "Azimuth":   f"{az.degrees:.1f}°",
                    "Direction": get_compass_dir(az.degrees),
                })
                sec += 60

            st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)

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
