import streamlit as st
import requests
import datetime
import pandas as pd
from suntime import Sun
import pytz

# --- 1. SETTINGS & SECRETS ---
st.set_page_config(page_title="Meteor-M Radio Passes", page_icon="🛰️", layout="wide")

try:
    API_KEY = st.secrets["N2YO_API_KEY"]
except:
    st.error("Missing N2YO_API_KEY!")
    st.stop()

# --- 2. SIDEBAR: CUSTOM LOCATION ---
st.sidebar.header("Location and threshold")

# Default, but user-adjustable
LAT = st.sidebar.number_input("Latitude", value=52.10, format="%.2f")
LNG = st.sidebar.number_input("Longitude", value=6.45, format="%.2f")
ALT = st.sidebar.number_input("Altitude (m)", value=18)

# Timezone Selection
all_tz = pytz.all_timezones
default_tz = all_tz.index("Europe/Amsterdam") if "Europe/Amsterdam" in all_tz else 0
selected_tz = st.sidebar.selectbox("Local Timezone", all_tz, index=default_tz)
LOCAL_TZ = pytz.timezone(selected_tz)

# Thresholds
MIN_EL = st.sidebar.slider("Min Elevation (Deg)", 10, 90, 50)
DAYS = st.sidebar.slider("Prediction Window (Days)", 1, 10, 10)

TARGET_SATS = {"Meteor M2-3": 57166, "Meteor M2-4": 59051}

# --- 3. HELPER FUNCTIONS ---
@st.cache_data(ttl=43200)
def get_passes(norad_id, name, lat, lng, alt, days, min_el):
    # The cache now triggers a fresh download if ANY sidebar value changes
    url = f"https://api.n2yo.com/rest/v1/satellite/radiopasses/{norad_id}/{lat}/{lng}/{alt}/{days}/{min_el}/&apiKey={API_KEY}"
    try:
        data = requests.get(url).json()
        return data.get('passes', [])
    except:
        return []

# --- 4. UI HEADER ---
st.title("🛰️ Meteor-M Pass Predictions")
st.subheader(f"Daylight Passes for {LAT}, {LNG}")
st.info("""
**Note to users:** This tool fetches real-time data from the **N2YO API**. 
To help the app stay within the daily API limits, please try to **minimize unnecessary refreshes** unless you have changed your settings by a lot. Happy hunting!
""")

# --- 5. MAIN LOGIC ---
sun = Sun(LAT, LNG)
all_data = []
rejected_passes = []

if st.button('Calculate/Refresh Pass Predictions'):
    with st.spinner('Comparing sweet passes...'):
        for name, sid in TARGET_SATS.items():
            passes = get_passes(sid, name, LAT, LNG, ALT, DAYS, MIN_EL)
            
            for p in passes:
                start_utc = datetime.datetime.fromtimestamp(p['startUTC'], datetime.timezone.utc)
                
                # Get Sunrise/Sunset
                srise_utc = sun.get_sunrise_time(start_utc)
                sset_utc = sun.get_sunset_time(start_utc)
                
                # Convert to minutes for robust comparison
                pass_min = start_utc.hour * 60 + start_utc.minute
                srise_min = srise_utc.hour * 60 + srise_utc.minute
                sset_min = sset_utc.hour * 60 + sset_utc.minute
                
                # 30-minute buffer
                if (srise_min - 30) <= pass_min <= (sset_min + 30):
                    start_dt_local = start_utc.astimezone(LOCAL_TZ)
                    duration_seconds = p['endUTC'] - p['startUTC']
                    
                    # --- CALCULATE PEAK DIRECTION ---
                    start_az = p['startAz']
                    end_az = p['endAz']

                    if abs(end_az - start_az) > 180:
                        if start_az > end_az:
                            avg_az = (start_az + end_az + 360) / 2
                        else:
                            avg_az = (start_az + end_az - 360) / 2
                    else:
                        avg_az = (start_az + end_az) / 2

                    avg_az %= 360 
                    directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
                    ix = int((avg_az + 11.25) / 22.5)
                    peak_compass = directions[ix % 16]

                    # This block must be indented exactly once more than the 'if' above it
                    all_data.append({
                        "Satellite": name,
                        "Local Time": start_dt_local.strftime('%d %b, %H:%M'),
                        "Max El": f"{p['maxEl']}° @ {peak_compass}",
                        "Direction": f"{p['startAzCompass']} ➔ {p['endAzCompass']}",
                        "Duration": f"{duration_seconds // 60}m {duration_seconds % 60}s",
                        "RawTime": p['startUTC']
                    })
                else:
                    # This 'else' must align perfectly with the 'if (srise_min - 30)...'
                    rejected_passes.append(f"❌ {name} at {start_utc.strftime('%H:%M')} UTC (Sun: {srise_utc.strftime('%H:%M')} - {sset_utc.strftime('%H:%M')})")

        if all_data:
            df = pd.DataFrame(all_data).sort_values("RawTime")
            next_pass = df.iloc[0]
            
            st.success(f"🎯 **Next Prime Capture:** {next_pass['Satellite']} at {next_pass['Local Time']}")
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Max Elevation", next_pass['Max El'])
            col2.metric("Pass Length", next_pass['Duration'])
            col3.metric("Path", next_pass['Direction'])
            
            st.divider()
            st.write("### 📅 Upcoming 10-Day Schedule")
            st.dataframe(df.drop(columns=["RawTime"]), use_container_width=True)
        else:
            st.warning("No elegible passes found for this location.")

        with st.expander("See Rejected 'Night' Passes"):
            for msg in rejected_passes:
                st.write(msg)

st.info(f"📍 Station: {LAT}, {LNG} | Threshold: {MIN_EL}° | Timezone: {selected_tz}")
