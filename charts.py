"""Plotly chart builders: sky plot and ground track map."""

import math

import plotly.graph_objects as go


def make_sky_plot(timeline: list[dict], sat_name: str) -> go.Figure:
    """
    Observer's sky view: N at top, E at right (as if lying on your back looking up).
    Elevation rings: 0° at edge, 90° at centre.
    """

    def azel_to_xy(az_deg: float, el_deg: float) -> tuple[float, float]:
        """Convert az/el to Cartesian x/y. N up, E right, horizon at r=1."""
        r = 1.0 - (el_deg / 90.0)
        az_r = math.radians(az_deg)
        return r * math.sin(az_r), r * math.cos(az_r)

    xs, ys, labels = [], [], []
    for r in timeline:
        x, y = azel_to_xy(r["az"], r["el"])
        xs.append(x)
        ys.append(y)
        labels.append(r["label"])

    # Minute markers (skip above 60° — spreads ugly near zenith)
    min_xs, min_ys, min_labels, min_positions = [], [], [], []
    last_min = None
    toggle = 0
    for r in timeline:
        from zoneinfo import ZoneInfo  # local import to avoid circular dep
        dt = r["t"].utc_datetime()  # label already formatted; use raw dt for minute check
        # Use the pre-formatted label to extract minute
        hh, mm, ss = r["label"].split(":")
        cur_min = int(mm)
        if int(ss) < 30 and last_min != cur_min and r["el"] < 60:
            x, y = azel_to_xy(r["az"], r["el"])
            min_xs.append(x)
            min_ys.append(y)
            min_labels.append(r["label"])
            min_positions.append("top right" if toggle % 2 == 0 else "top left")
            toggle += 1
            last_min = cur_min

    peak_idx = max(range(len(timeline)), key=lambda i: timeline[i]["el"])
    px, py = azel_to_xy(timeline[peak_idx]["az"], timeline[peak_idx]["el"])

    fig = go.Figure()

    # Elevation rings
    for el_ring, ring_label in [(0, "0°"), (30, "30°"), (60, "60°"), (90, "90°")]:
        r = 1.0 - el_ring / 90.0
        angles = [i * math.pi / 180 for i in range(361)]
        fig.add_trace(go.Scatter(
            x=[r * math.sin(a) for a in angles],
            y=[r * math.cos(a) for a in angles],
            mode="lines",
            line=dict(color="rgba(255,255,255,0.15)", width=1),
            hoverinfo="skip", showlegend=False,
        ))
        if el_ring < 90:
            fig.add_annotation(
                x=0, y=-r, text=ring_label,
                font=dict(color="rgba(255,255,255,0.5)", size=9),
                showarrow=False, yshift=-8,
            )

    # Cardinal direction lines & labels
    for az_deg, card_label in [(0, "N"), (90, "E"), (180, "S"), (270, "W")]:
        az_r = math.radians(az_deg)
        fig.add_trace(go.Scatter(
            x=[0, math.sin(az_r)], y=[0, math.cos(az_r)],
            mode="lines",
            line=dict(color="rgba(255,255,255,0.2)", width=1),
            hoverinfo="skip", showlegend=False,
        ))
        fig.add_annotation(
            x=1.08 * math.sin(az_r), y=1.08 * math.cos(az_r),
            text=f"<b>{card_label}</b>",
            font=dict(color="white", size=13),
            showarrow=False,
        )

    # Pass arc
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="lines",
        line=dict(color="#00aaff", width=3),
        hovertext=labels, hoverinfo="text", showlegend=False,
    ))

    # AOS
    fig.add_trace(go.Scatter(
        x=[xs[0]], y=[ys[0]], mode="markers+text",
        marker=dict(color="lime", size=12),
        text=["AOS"], textposition="top center",
        hoverinfo="skip", showlegend=False,
    ))

    # LOS
    fig.add_trace(go.Scatter(
        x=[xs[-1]], y=[ys[-1]], mode="markers+text",
        marker=dict(color="red", size=12),
        text=["LOS"], textposition="top center",
        hoverinfo="skip", showlegend=False,
    ))

    # Peak
    fig.add_trace(go.Scatter(
        x=[px], y=[py], mode="markers+text",
        marker=dict(color="orange", size=14, symbol="star"),
        text=[f"MAX {int(timeline[peak_idx]['el'])}°"],
        textposition="top center",
        hoverinfo="skip", showlegend=False,
    ))

    # Minute markers
    for i in range(len(min_xs)):
        fig.add_trace(go.Scatter(
            x=[min_xs[i]], y=[min_ys[i]], mode="markers+text",
            marker=dict(color="yellow", size=7),
            text=[min_labels[i]], textposition=min_positions[i],
            textfont=dict(size=9), hoverinfo="skip", showlegend=False,
        ))

    fig.update_layout(
        xaxis=dict(range=[-1.2, 1.2], visible=False, scaleanchor="y"),
        yaxis=dict(range=[-1.2, 1.2], visible=False),
        plot_bgcolor="rgb(0,10,30)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=20, b=20),
        height=420,
    )
    return fig


def make_ground_track(
    timeline: list[dict],
    sat_name: str,
    observer_lat: float,
    observer_lon: float,
) -> go.Figure:
    """Ground track map with AOS/LOS markers, minute ticks, and observer location."""
    lats   = [r["lat"] for r in timeline]
    lons   = [r["lon"] for r in timeline]
    labels = [r["label"] for r in timeline]

    # Minute markers
    min_lats, min_lons, min_labels = [], [], []
    last_min = None
    for r in timeline:
        hh, mm, ss = r["label"].split(":")
        cur_min = int(mm)
        if int(ss) < 30 and last_min != cur_min:
            min_lats.append(r["lat"])
            min_lons.append(r["lon"])
            min_labels.append(r["label"])
            last_min = cur_min

    fig = go.Figure()

    fig.add_trace(go.Scattergeo(
        lat=lats, lon=lons, mode="lines",
        line=dict(color="#00aaff", width=2.5),
        name=sat_name, hovertext=labels, hoverinfo="text",
    ))
    fig.add_trace(go.Scattergeo(
        lat=min_lats, lon=min_lons, mode="markers+text",
        marker=dict(color="yellow", size=7),
        text=min_labels, textposition="top right",
        textfont=dict(size=9, color="yellow"),
        name="Minutes", hoverinfo="skip",
    ))
    fig.add_trace(go.Scattergeo(
        lat=[lats[0], lats[-1]], lon=[lons[0], lons[-1]],
        mode="markers+text",
        marker=dict(color=["lime", "red"], size=12),
        text=["AOS", "LOS"], textposition="top center",
        textfont=dict(color="white"), hoverinfo="skip",
    ))
    fig.add_trace(go.Scattergeo(
        lat=[observer_lat], lon=[observer_lon],
        mode="markers+text",
        marker=dict(color="orange", size=10, symbol="star"),
        text=["You"], textposition="top right",
        textfont=dict(color="orange"), hoverinfo="skip",
    ))

    pad = 15
    fit_lats = lats + [observer_lat]
    fit_lons = lons + [observer_lon]
    lat_min = max(-80, min(fit_lats) - pad)
    lat_max = min(85,  max(fit_lats) + pad)
    lon_min = min(fit_lons) - pad
    lon_max = max(fit_lons) + pad

    fig.update_geos(
        projection_type="mercator",
        showland=True,       landcolor="rgb(40,60,40)",
        showocean=True,      oceancolor="rgb(10,20,50)",
        showcoastlines=True, coastlinecolor="rgba(255,255,255,0.4)",
        showcountries=True,  countrycolor="rgba(255,255,255,0.3)",
        bgcolor="rgba(0,0,0,0)",
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=20, b=20),
        showlegend=False,
        height=420,
        geo=dict(
            lataxis=dict(range=[lat_min, lat_max]),
            lonaxis=dict(range=[lon_min, lon_max]),
        ),
    )
    return fig
