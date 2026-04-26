"""Sidebar form: location, timezone and filter settings."""
 
import streamlit as st
from timezone_utils import make_tz_options
 
def render_sidebar(available_sat_names: list[str], browser_tz: str | None) -> dict:
    """
    Render the sidebar form and return a dict of the current settings.
 
    Keys returned:
        lat, lng, alt, use_auto_tz, manual_tz, min_el, days,
        show_night, selected_sats
    """
    with st.sidebar.form("location_form"):
        st.header("📍 Location & Settings")
 
        new_lat = st.number_input("Latitude",      value=52.10, format="%.4f")
        new_lng = st.number_input("Longitude",     value=6.45,  format="%.4f")
        new_alt = st.number_input("Altitude (m)",  value=18)
 
        # --- Timezone ---
        st.subheader("🕒 Timezone")
        use_auto_tz = st.checkbox("Use browser timezone", value=True)
 
        if browser_tz:
            st.caption(
                f"Detected: **{browser_tz}**. "
                "To use a manual offset instead, uncheck the box above, "
                "click Apply, then choose your offset and click Apply again."
            )
        else:
            st.caption(
                "Browser timezone could not be detected. "
                "Uncheck the box above, click Apply, then select a manual offset."
            )
 
        tz_options = make_tz_options()
        default_tz = "UTC+02:00"
        default_idx = tz_options.index(default_tz) if default_tz in tz_options else 0
 
        new_tz = st.selectbox(
            "Manual UTC offset",
            tz_options,
            index=default_idx,
            disabled=use_auto_tz,
        )
 
        new_el   = st.slider("Min Elevation (°)",         0, 90, 10)
        new_days = st.slider("Prediction Window (Days)",  1, 10,  5)
        show_night = st.checkbox("Show Night passes", value=False)
 
        selected_sats = st.multiselect(
            "Satellites",
            options=available_sat_names,
            default=available_sat_names,
        )
 
        st.form_submit_button("Apply")
 
    return {
        "lat":           max(-90.0,  min(90.0,  new_lat)),
        "lng":           max(-180.0, min(180.0, new_lng)),
        "alt":           max(0,      min(8848,  int(new_alt))),
        "use_auto_tz":   use_auto_tz,
        "manual_tz":     new_tz,
        "min_el":        new_el,
        "days":          new_days,
        "show_night":    show_night,
        "selected_sats": selected_sats,
    }
 
 
def render_tle_age(fetched_at: str) -> None:
    """Show TLE data age in the sidebar (outside the form)."""
    import datetime
    with st.sidebar:
        try:
            age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(fetched_at)
            hours_ago = int(age.total_seconds() // 3600)
            if hours_ago > 72:
                st.warning(f"⚠️ TLEs are {hours_ago}h old — predictions may be inaccurate.")
            else:
                st.caption(f"🕐 TLE data: {hours_ago}h ago")
        except Exception:
            st.caption(f"🕐 TLE fetched at: {fetched_at}")
