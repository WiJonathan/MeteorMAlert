# 🛰️ Meteor-M & MetOp Pass Predictor
 
A Streamlit app that predicts upcoming passes of Meteor-M and MetOp weather satellites over your location, with sky plots, ground tracks, and minute-by-minute tracking tables.
 
![Python](https://img.shields.io/badge/python-3.11+-blue) ![Streamlit](https://img.shields.io/badge/streamlit-1.x-red) ![License](https://img.shields.io/badge/license-GPL--3.0-green)
 
## Features
 
- Finds all visible passes within a configurable window (1–10 days)
- Filter by minimum elevation threshold, day/night toggle, per-satellite selection
- Observer's-eye view with AOS/LOS markers, peak elevation, and minute ticks
- Mercator map showing the satellite's path during the pass
- Minute-by-minute table showing azimuth, elevation, and compass direction throughout the pass
- Auto-detects browser timezone or accepts a manual UTC offset
- Warns when orbital data is older than 72 hours
## Project Structure
 
```
├── appMETEOR.py              # Entry point
├── charts.py           # Sky plot and ground track (Plotly)
├── predictions.py      # Pass finding and timeline computation
├── sidebar.py          # Sidebar UI
├── tle_utils.py        # TLE loading and satellite helpers
├── timezone_utils.py   # Timezone parsing and resolution
└── tles.json           # TLE data (not in repo — see Setup)
```
 
## Setup
 
Requires Python 3.11+
 
```bash
pip install streamlit skyfield plotly pandas streamlit-js-eval
```
 
You'll need a `tles.json` file in the project root. The expected format is:
 
```json
{
  "fetched_at": "2025-01-01T12:00:00+00:00",
  "satellites": {
    "METEOR-M2-3": {
      "name": "METEOR-M2-3",
      "tle_line1": "1 57166U ...",
      "tle_line2": "2 57166 ..."
    }
  }
}
```
 
TLEs are automatically refreshed every 12 hours via a GitHub Actions workflow, so `tles.json` is always kept up to date. The app will warn you if the data is ever more than 72 hours old.
 
## Running
 
```bash
streamlit run app.py
```
 
## Usage
 
1. Enter your latitude, longitude, and altitude in the sidebar
2. Set your timezone (auto-detected from the browser, or pick a manual UTC offset)
3. Adjust the minimum elevation and prediction window
4. Click Apply
5. Click any row in the pass table to see the sky plot and ground track for that pass
## Contributing
 
This is a personal project but if you're into weather satellite reception and want to contribute, feel free to get in touch.
 
## Satellites Covered
 
- Meteor-M series (Russian weather satellites, 137 MHz LRPT / 1.7 GHz HRPT)
- MetOp series (EUMETSAT polar orbiters, 1.7 GHz AHRPT)
