import streamlit as st
import requests
import datetime
import pandas as pd
from suntime import Sun
import pytz

# --- 1. SETTINGS & SECRETS ---
st.set_page_config(page_title="Meteor-M Ground Station", page_icon="🛰️", layout="wide")

# This pulls from .streamlit/secrets.toml OR Streamlit Cloud Secrets
try:
    API_KEY = st.secrets["N2YO_API_KEY"]
except:
    st.error("Missing N2YO_API_KEY!")
    st.stop()

# Station Location
LAT, LNG, ALT = 52.10, 6.45, 18 
LOCAL_TZ = pytz.timezone("Europe/Amsterdam")

# Satellite IDs (Meteor-M series and NOAA for overlap check)
TARGET_SATS = {"Meteor M2-3": 57166, "Meteor M2-4": 59051}
NOAA_SATS = {"NOAA 15": 25338, "NOAA 18": 28654, "NOAA 19": 33591}

MIN_EL = 50
DAYS = 10

# --- 2. HELPER FUNCTIONS ---
def get_passes(norad_id, name):
    url = f"https://api.n2yo.com/rest/v1/satellite/radiopasses/{norad_id}/{LAT}/{LNG}/{ALT}/{DAYS}/{MIN_EL}/&apiKey={API_KEY}"
    try:
        data = requests.get(url).json()
        return data.get('passes', [])
    except:
        return []

def to_local(utc_ts):
    utc_dt = datetime.datetime.fromtimestamp(utc_ts, datetime.timezone.utc)
    return utc_dt.astimezone(LOCAL_TZ)

# --- 3. UI HEADER ---
st.title("🛰️ Meteor-M Radio Passes Ruurlo")
st.subheader("Daylight Passes > 50° Elevation")

# --- 4. MAIN LOGIC (REVISED) ---
sun = Sun(LAT, LNG)
all_data = []
rejected_passes = [] # To help debug!

if st.button('Refresh Pass Predictions'):
    with st.spinner('Calculating orbits and solar angles...'):
        for name, sid in TARGET_SATS.items():
            passes = get_passes(sid, name)
            for p in passes:
                start_utc = datetime.datetime.fromtimestamp(p['startUTC'], datetime.timezone.utc)
                
                # Get Sunrise/Sunset
                srise_utc = sun.get_sunrise_time(start_utc)
                sset_utc = sun.get_sunset_time(start_utc)
                
                # CONVERT EVERYTHING TO MINUTES FROM MIDNIGHT
                pass_min = start_utc.hour * 60 + start_utc.minute
                srise_min = srise_utc.hour * 60 + srise_utc.minute
                sset_min = sset_utc.hour * 60 + sset_utc.minute
                
                # Add 30-minute buffer
                srise_min -= 30
                sset_min += 30

                # Simple math comparison
                if srise_min <= pass_min <= sset_min:
                    start_dt_local = start_utc.astimezone(LOCAL_TZ)
                    duration_seconds = p['endUTC'] - p['startUTC']
                    all_data.append({
                        "Satellite": name,
                        "Local Time": start_dt_local.strftime('%d %b, %H:%M'),
                        "Max El": f"{p['maxEl']}°",
                        "Direction": f"{p['startAzCompass']} ➔ {p['endAzCompass']}",
                        "Duration": f"{duration_seconds // 60}m {duration_seconds % 60}s",
                        "RawTime": p['startUTC']
                    })
                else:
                    rejected_passes.append(f"❌ {name} at {start_utc.strftime('%H:%M')} UTC (Sun: {srise_utc.strftime('%H:%M')} - {sset_utc.strftime('%H:%M')})")

        if all_data:
            df = pd.DataFrame(all_data).sort_values("RawTime")
            next_pass = df.iloc[0]
            st.success(f"🎯 **Next Prime Capture:** {next_pass['Satellite']} at {next_pass['Local Time']}")
            
            # (Metrics code stays the same...)
            col1, col2, col3 = st.columns(3)
            col1.metric("Max Elevation", next_pass['Max El'])
            col2.metric("Pass Length", next_pass['Duration'])
            col3.metric("Path", next_pass['Direction'])
            st.divider()
            st.dataframe(df.drop(columns=["RawTime"]), use_container_width=True)
        else:
            st.warning("No high-elevation daylight passes found.")
            
        # DEBUG SECTION (Only shows if you click it)
        with st.expander("See Rejected 'Night' Passes"):
            for msg in rejected_passes:
                st.write(msg)

st.info(f"📍 Station: {LAT}, {LNG} | Threshold: {MIN_EL}° | Timezone: CEST")
