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
with st.sidebar.form("location_form"):
    show_night = st.sidebar.checkbox("Show Nigh passes", value=False)
    st.header("Location and threshold")
    st.write("Adjust settings and click apply to update.")
    
    # Inputs inside the form don't trigger a rerun until the button is pressed
    new_lat = st.number_input("Latitude", value=52.10, format="%.2f")
    new_lng = st.number_input("Longitude", value=6.45, format="%.2f")
    new_alt = st.number_input("Altitude (m)", value=18)
    
    all_tz = pytz.all_timezones
    default_tz_idx = all_tz.index("Europe/Amsterdam") if "Europe/Amsterdam" in all_tz else 0
    new_tz = st.selectbox("Local Timezone", all_tz, index=default_tz_idx)
    
    new_el = st.slider("Min Elevation (Deg)", 10, 90, 50)
    new_days = st.slider("Prediction Window (Days)", 1, 10, 10)
    
    # THE TRIGGER
    submitted = st.form_submit_button("Apply & recalculate")

# Global variables assigned from the form
LAT, LNG, ALT = new_lat, new_lng, new_alt
LOCAL_TZ = pytz.timezone(new_tz)
MIN_EL, DAYS = new_el, new_days

TARGET_SATS = {"Meteor M2-3": 57166, "Meteor M2-4": 59051}

# --- 3. HELPER FUNCTIONS ---
@st.cache_data(ttl=43200)
def get_passes(norad_id, name, lat, lng, alt, days, min_el):
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
To help the app stay within the daily API limits, please try to **minimize unnecessary settings changes**, which removes the cached schedule and refetches it. Happy hunting!
""")

# --- 5. MAIN LOGIC ---
sun = Sun(LAT, LNG)
all_data = []
rejected_passes = []

# Get the current time in the user's selected timezone
now = datetime.datetime.now(LOCAL_TZ)

with st.spinner('Updating orbital schedule...'):
    for name, sid in TARGET_SATS.items():
        # Using the same cached function
        passes = get_passes(sid, name, LAT, LNG, ALT, DAYS, MIN_EL)
        
        for p in passes:
            # Convert pass time to Local Time for comparison
            start_utc = datetime.datetime.fromtimestamp(p['startUTC'], datetime.timezone.utc)
            start_dt_local = start_utc.astimezone(LOCAL_TZ)
            end_dt_local = datetime.datetime.fromtimestamp(p['endUTC'], datetime.timezone.utc).astimezone(LOCAL_TZ)
            
            # 1. FILTER: Only keep passes that end in the FUTURE
            if end_dt_local < now:
                continue

            # 2. SUNLIGHT CHECK
            srise_utc = sun.get_sunrise_time(start_utc)
            sset_utc = sun.get_sunset_time(start_utc)
            
            pass_min = start_utc.hour * 60 + start_utc.minute
            srise_min = (srise_utc.hour * 60 + srise_utc.minute) - 30
            sset_min = (sset_utc.hour * 60 + sset_utc.minute) + 30
            
            if show_night or srise_min <= pass_min <= sset_min:
                duration_seconds = p['endUTC'] - p['startUTC']
                
                # --- PEAK DIRECTION CALC ---
                start_az, end_az = p['startAz'], p['endAz']
                if abs(end_az - start_az) > 180:
                    avg_az = (start_az + end_az + (360 if start_az < end_az else -360)) / 2
                else:
                    avg_az = (start_az + end_az) / 2
                avg_az %= 360
                
                dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
                peak_compass = dirs[int((avg_az + 11.25) / 22.5) % 16]

                all_data.append({
                    "Satellite": name,
                    "Local Time": start_dt_local.strftime('%d %b, %H:%M'),
                    "Max El": f"{p['maxEl']}° @ {peak_compass}",
                    "Direction": f"{p['startAzCompass']} ➔ {p['endAzCompass']}",
                    "Duration": f"{duration_seconds // 60}m {duration_seconds % 60}s",
                    "RawTime": p['startUTC']
                })
            else:
                rejected_passes.append(f"❌ {name} at {start_dt_local.strftime('%H:%M')} (Night)")

    # --- DISPLAY RESULTS ---
    if all_data:
        df = pd.DataFrame(all_data).sort_values("RawTime")
        next_pass = df.iloc[0]
        
        st.success(f"🎯 **Next pass:** {next_pass['Satellite']} at {next_pass['Local Time']}")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Max Elevation", next_pass['Max El'])
        col2.metric("Pass Length", next_pass['Duration'])
        col3.metric("Path", next_pass['Direction'])
        
        st.divider()
        st.write("### 📅 Upcoming 10-Day Schedule")
        st.dataframe(df.drop(columns=["RawTime"]), use_container_width=True)
    else:
        st.warning("No eligible future passes found for this location.")

    with st.expander("See Rejected Night Passes"):
        for msg in rejected_passes:
            st.write(msg)

st.info(f"📍 Location: {LAT}, {LNG} | Threshold: {MIN_EL}° | Timezone: {new_tz}")
