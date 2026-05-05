import datetime
import pandas as pd
import streamlit as st
from streamlit_js_eval import streamlit_js_eval
from charts import make_ground_track, make_sky_plot
from predictions import compute_pass_timeline, find_passes
from sidebar import render_sidebar, render_tle_age
from tle_utils import get_available_satellite_names, load_satellites, make_observer, ts
from timezone_utils import resolve_timezone

# Page config
st.set_page_config(
    page_title="Meteor-M and MetOp TLE Predictor",
    page_icon="🛰️",
    layout="wide",
)

# Browser timezone detection (cached in session_state to avoid cascade reruns)
if "browser_tz" not in st.session_state:
    st.session_state["browser_tz"] = None

browser_tz_raw = streamlit_js_eval(
    js_expressions="Intl.DateTimeFormat().resolvedOptions().timeZone",
    key="tz",
)
if browser_tz_raw and st.session_state["browser_tz"] != browser_tz_raw:
    st.session_state["browser_tz"] = browser_tz_raw
    st.rerun()

browser_tz: str | None = st.session_state["browser_tz"]

# Sidebar
available_sat_names = get_available_satellite_names()
settings = render_sidebar(available_sat_names, browser_tz)

LAT  = settings["lat"]
LNG  = settings["lng"]
ALT  = settings["alt"]
MIN_EL     = settings["min_el"]
DAYS       = settings["days"]
SHOW_NIGHT = settings["show_night"]
SELECTED   = settings["selected_sats"]

LOCAL_TZ = resolve_timezone(
    use_auto=settings["use_auto_tz"],
    browser_tz=browser_tz,
    manual_tz_str=settings["manual_tz"],
)

# Load TLEs
tles, fetched_at = load_satellites(SELECTED)

if not tles:
    st.error("`tles.json` not found or contains no matching satellites.")
    st.stop()

render_tle_age(fetched_at)

# Compute passes
observer = make_observer(LAT, LNG, ALT)
now = datetime.datetime.now(datetime.timezone.utc)
t0  = ts.from_datetime(now)
t1  = ts.from_datetime(now + datetime.timedelta(days=DAYS))

with st.spinner("Calculating passes..."):
    all_data, pass_objects, rejected_passes = find_passes(
        tles=tles,
        observer_topos=observer,
        t0=t0,
        t1=t1,
        lat=LAT,
        lng=LNG,
        min_el=MIN_EL,
        show_night=SHOW_NIGHT,
        local_tz=LOCAL_TZ,
    )

# Main title
st.title("🛰️ Meteor-M and MetOp Pass Predictor")

# Pass table
if not all_data:
    st.warning("No eligible passes found. Try lowering min elevation or enabling night passes.")
else:
    df = pd.DataFrame(all_data).sort_values("RawTime").reset_index(drop=True)
    sorted_indices    = list(pd.DataFrame(all_data).sort_values("RawTime").index)
    sorted_pass_objects = [pass_objects[i] for i in sorted_indices]

    # Next pass summary
    next_pass = df.iloc[0]
    st.success(f"🎯 **Next pass:** {next_pass['Satellite']} — {next_pass['Local Time']}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Max Elevation",  next_pass["Max El"])
    c2.metric("Peak Direction", next_pass["Peak Direction"])
    c3.metric("Duration",       next_pass["Duration"])
    c4.metric("Path",           next_pass["Path"])

    st.divider()
    st.subheader(f"All passes — next {DAYS} day(s)")
    st.caption("Click a row to see the sky plot and satellite path.")

    display_df = df.drop(columns=["RawTime"]).copy()
    selection  = st.dataframe(
        display_df,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
    )

    selected_rows = selection.selection.rows
    if selected_rows:
        st.session_state["selected_pass"] = selected_rows[0]

    # Detail view
    if "selected_pass" in st.session_state:
        sel_idx = st.session_state["selected_pass"]
        if sel_idx < len(sorted_pass_objects):
            p = sorted_pass_objects[sel_idx]
            sat = p["sat"]
            t_rise, t_peak, t_set = p["t_rise"], p["t_peak"], p["t_set"]
            row = df.iloc[sel_idx]

            st.divider()
            st.subheader(f"{row['Satellite']} — {row['Local Time']}")

            timeline = compute_pass_timeline(sat, observer, t_rise, t_set, LOCAL_TZ)

            col_plot, _ = st.columns([1, 1])
            with col_plot:
                st.markdown("**Sky Plot**")
                st.plotly_chart(
                    make_sky_plot(timeline, sat.name),
                    use_container_width=True,
                    key="skyplot",
                )
                st.markdown("**Satellite Path**")
                st.plotly_chart(
                    make_ground_track(timeline, sat.name, LAT, LNG),
                    use_container_width=True,
                    key="groundtrack",
                )

            # Minute-by-minute table
            st.markdown("**Minute-by-minute tracking**")
            duration_s = (t_set - t_rise) * 24 * 3600
            from tle_utils import get_compass_dir
            table_rows = []
            sec = 0
            while sec <= duration_s:
                frac = sec / duration_s
                t_sample = t_rise + frac * (t_set - t_rise)
                diff = (sat - observer).at(t_sample)
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

# Rejected passes expander
with st.expander(f"Rejected passes ({len(rejected_passes)})"):
    for msg in rejected_passes:
        st.write(msg)
    if not rejected_passes:
        st.write("None.")
