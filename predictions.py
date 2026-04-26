"""Satellite pass prediction and astronomy helper functions."""

import math
import datetime

from skyfield.api import EarthSatellite, Topos, wgs84

from tle_utils import ts, get_compass_dir


# Sun / daytime helpers
def sun_elevation_deg(dt_utc: datetime.datetime, lat_deg: float, lng_deg: float) -> float:
    """Return approximate solar elevation (degrees) for a given UTC datetime and location."""
    n = dt_utc.timetuple().tm_yday
    decl = 23.45 * math.sin(math.radians((360 / 365) * (n - 81)))
    B = math.radians((360 / 365) * (n - 81))
    eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)
    solar_time = (
        dt_utc.hour * 60 + dt_utc.minute + dt_utc.second / 60
        + lng_deg * 4 + eot
    )
    hour_angle = (solar_time / 4) - 180
    lat_r = math.radians(lat_deg)
    decl_r = math.radians(decl)
    ha_r = math.radians(hour_angle)
    sin_el = (
        math.sin(lat_r) * math.sin(decl_r)
        + math.cos(lat_r) * math.cos(decl_r) * math.cos(ha_r)
    )
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_el))))


def is_daytime(t, lat: float, lng: float, horizon_deg: float = -6.0) -> bool:
    """Return True if the sun is above horizon_deg at time t."""
    return sun_elevation_deg(t.utc_datetime(), lat, lng) > horizon_deg

# Pass timeline
def compute_pass_timeline(
    sat: EarthSatellite,
    observer_topos: Topos,
    t_rise,
    t_set,
    local_tz,
) -> list[dict]:
    """
    Compute az/el/lat/lon/bearing at ~30-second intervals from AOS to LOS.

    Returns a list of dicts with keys:
        t, el, az, lat, lon, bearing, label
    """
    duration_s = (t_set - t_rise) * 24 * 3600
    steps = max(2, int(duration_s / 30))
    rows = []

    for i in range(steps + 1):
        frac = i / steps
        t = t_rise + frac * (t_set - t_rise)
        diff = (sat - observer_topos).at(t)
        el, az, _ = diff.altaz()
        geo = wgs84.subpoint_of(sat.at(t))

        # Bearing from velocity vector in Earth-fixed frame
        pos_vel = sat.at(t)
        vxyz = pos_vel.velocity.km_per_s
        lat_r = math.radians(geo.latitude.degrees)
        lon_r = math.radians(geo.longitude.degrees)
        east  = [-math.sin(lon_r), math.cos(lon_r), 0.0]
        north = [
            -math.sin(lat_r) * math.cos(lon_r),
            -math.sin(lat_r) * math.sin(lon_r),
             math.cos(lat_r),
        ]
        v_east  = sum(vxyz[j] * east[j]  for j in range(3))
        v_north = sum(vxyz[j] * north[j] for j in range(3))
        bearing = math.degrees(math.atan2(v_east, v_north)) % 360

        rows.append({
            "t":       t,
            "el":      max(0.0, el.degrees),
            "az":      az.degrees,
            "lat":     geo.latitude.degrees,
            "lon":     geo.longitude.degrees,
            "bearing": bearing,
            "label":   t.astimezone(local_tz).strftime("%H:%M:%S"),
        })

    return rows


# Pass finding
def find_passes(
    tles: list[EarthSatellite],
    observer_topos: Topos,
    t0,
    t1,
    lat: float,
    lng: float,
    min_el: float,
    show_night: bool,
    local_tz,
) -> tuple[list[dict], list[dict], list[str]]:
    """
    Find all satellite passes within [t0, t1].

    Returns:
        all_data        – list of display-ready dicts (one per pass)
        pass_objects    – list of raw pass dicts (sat, t_rise, t_peak, t_set)
        rejected_passes – list of human-readable rejection messages
    """
    all_data = []
    pass_objects = []
    rejected_passes = []

    for sat in tles:
        try:
            times, events = sat.find_events(observer_topos, t0, t1, altitude_degrees=0)
        except Exception as e:
            import streamlit as st
            st.warning(f"⚠️ Error computing passes for {sat.name}: {e}")
            continue

        i = 0
        while i < len(events):
            if (
                events[i] == 0
                and i + 2 < len(events)
                and events[i + 1] == 1
                and events[i + 2] == 2
            ):
                t_rise, t_peak, t_set = times[i], times[i + 1], times[i + 2]

                diff_peak_check = (sat - observer_topos).at(t_peak)
                el_check, _, _ = diff_peak_check.altaz()
                if el_check.degrees < min_el:
                    i += 3
                    continue

                daytime = is_daytime(t_rise, lat, lng)

                if show_night or daytime:
                    diff_rise = (sat - observer_topos).at(t_rise)
                    diff_peak = (sat - observer_topos).at(t_peak)
                    diff_set  = (sat - observer_topos).at(t_set)

                    el_peak, az_peak, _ = diff_peak.altaz()
                    _,       az_rise, _ = diff_rise.altaz()
                    _,       az_set,  _ = diff_set.altaz()

                    duration_s = (t_set - t_rise) * 24 * 3600

                    all_data.append({
                        "Satellite":      sat.name,
                        "Local Time":     t_rise.astimezone(local_tz).strftime("%d %b, %H:%M"),
                        "Max El":         f"{int(el_peak.degrees)}°",
                        "Peak Direction": get_compass_dir(az_peak.degrees),
                        "Path":           f"{get_compass_dir(az_rise.degrees)} ➔ {get_compass_dir(az_set.degrees)}",
                        "Duration":       f"{int(duration_s // 60)}m {int(duration_s % 60)}s",
                        "RawTime":        t_rise.tt,
                    })
                    pass_objects.append({
                        "sat":    sat,
                        "t_rise": t_rise,
                        "t_peak": t_peak,
                        "t_set":  t_set,
                    })
                else:
                    rejected_passes.append(
                        f"❌ {sat.name} at "
                        f"{t_rise.astimezone(local_tz).strftime('%d %b %H:%M')} — Night pass"
                    )
                i += 3
            else:
                i += 1

    return all_data, pass_objects, rejected_passes
