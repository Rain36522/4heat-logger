"""Plotly.js figure specifications built as plain dicts (no plotly Python package, no Django).

Colours are tokens such as "$series-1". The page replaces each token with the value of
the matching CSS custom property (--series-1), so light and dark mode both work and the
palette lives in one place (base.html). Series colours follow the dataviz palette:
  boiler = series 1, exhaust = series 2, oxygen = series 3 (fixed per quantity),
  neutral inks for target / state / journal markers, "critical" only for defects.
"""

from __future__ import annotations

import bisect
from datetime import timedelta

import pandas as pd

from .readings import ErrorEpisode, between, insert_gap_breaks

TOKENS = {
    "$surface", "$ink", "$ink2", "$muted", "$grid", "$axis",
    "$series-1", "$series-2", "$series-3", "$critical",
    "$ramp0", "$ramp1", "$ramp2", "$ramp3", "$ramp4", "$ramp5",
}

FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# metric -> (label, unit, d3 number format)
METRICS = {
    "boiler_temp": ("Chaudière", "°C", ".0f"),
    "exhaust_temp": ("Fumées", "°C", ".0f"),
    "oxygen_percent": ("O₂", "%", ".2f"),
    "state": ("État", "", ".0f"),
}

CONFIG = {
    "responsive": True,
    "displaylogo": False,
    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
}


def _number(value):
    return None if value is None or pd.isna(value) else float(value)


def _values(frame: pd.DataFrame, column: str) -> list:
    return [_number(value) for value in frame[column].tolist()]


def _times(frame: pd.DataFrame) -> list[str]:
    return [moment.strftime(TIME_FORMAT) for moment in frame["timestamp"]]


def _axis(**extra) -> dict:
    """Recessive hairline axis: solid grid, one step off the surface."""
    axis = {
        "gridcolor": "$grid",
        "gridwidth": 1,
        "zeroline": False,
        "linecolor": "$axis",
        "linewidth": 1,
        "tickfont": {"color": "$muted", "size": 11},
        "automargin": True,
    }
    axis.update(extra)
    return axis


def _title(text: str) -> dict:
    return {"text": text, "font": {"color": "$ink2", "size": 12}, "standoff": 8}


def _line(name, x, y, color, yaxis, hover, width=2, shape="linear", text=None) -> dict:
    trace = {
        "type": "scatter",
        "mode": "lines",
        "name": name,
        "x": x,
        "y": y,
        "xaxis": "x",
        "yaxis": yaxis,
        "line": {"color": color, "width": width, "shape": shape},
        "connectgaps": False,
        "hovertemplate": hover + "<extra></extra>",
    }
    if text is not None:
        trace["text"] = text
    return trace


def _empty_spec(message: str) -> dict:
    return {
        "data": [],
        "layout": {
            "paper_bgcolor": "$surface",
            "plot_bgcolor": "$surface",
            "xaxis": {"visible": False},
            "yaxis": {"visible": False},
            "annotations": [
                {
                    "text": message,
                    "showarrow": False,
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "font": {"color": "$ink2", "size": 14, "family": FONT},
                }
            ],
        },
        "config": CONFIG,
    }


def build_timeline_spec(
    readings: pd.DataFrame,
    episodes: list[ErrorEpisode],
    changes: list[tuple],
    state_names: dict[int, str] | None = None,
) -> dict:
    """Three stacked panels sharing one time axis: temperatures, oxygen, state.

    Defects are shaded bands labelled with their code; settings changes (journal) are
    thin vertical lines with a diamond marker that carries the details on hover.
    `changes` is a list of (datetime, "T06: 120 → 240") tuples.
    """
    if readings.empty:
        return _empty_spec("Aucune donnée sur cette période")
    state_names = state_names or {}
    frame = insert_gap_breaks(readings)
    x = _times(frame)

    state_text = [
        "" if pd.isna(value) or int(value) not in state_names else f" — {state_names[int(value)]}"
        for value in frame["state"]
    ]
    traces = [
        _line("Chaudière", x, _values(frame, "boiler_temp"), "$series-1", "y3", "%{y:.0f} °C"),
        _line("Fumées", x, _values(frame, "exhaust_temp"), "$series-2", "y3", "%{y:.0f} °C"),
        _line("Consigne", x, _values(frame, "boiler_target_temp"), "$ink2", "y3", "%{y:.0f} °C", width=1.5),
        _line("O₂", x, _values(frame, "oxygen_percent"), "$series-3", "y2", "%{y:.2f} %"),
        _line("État", x, _values(frame, "state"), "$ink", "y", "%{y:.0f}%{text}", width=1.5, shape="hv", text=state_text),
    ]

    shapes, annotations = [], []
    for episode in episodes:
        start = episode.start.strftime(TIME_FORMAT)
        end = (episode.last_seen + timedelta(seconds=60)).strftime(TIME_FORMAT)
        shapes.append(
            {
                "type": "rect", "xref": "x", "yref": "paper", "x0": start, "x1": end, "y0": 0, "y1": 1,
                "fillcolor": "$critical", "opacity": 0.14, "line": {"width": 0}, "layer": "below",
            }
        )
        annotations.append(
            {
                "x": start, "xref": "x", "y": 1, "yref": "paper", "text": f"⚠ {episode.code}",
                "showarrow": False, "xanchor": "left", "yanchor": "bottom",
                "font": {"size": 11, "color": "$ink", "family": FONT},
            }
        )

    grouped: dict = {}
    for moment, label in changes:
        grouped.setdefault(moment, []).append(label)
    if grouped:
        temperatures = [
            value
            for column in ("boiler_temp", "exhaust_temp", "boiler_target_temp")
            for value in frame[column].dropna()
        ]
        top = float(max(temperatures)) if temperatures else 100.0
        moments = sorted(grouped)
        for moment in moments:
            stamp = moment.strftime(TIME_FORMAT)
            shapes.append(
                {
                    "type": "line", "xref": "x", "yref": "paper", "x0": stamp, "x1": stamp, "y0": 0, "y1": 1,
                    "line": {"color": "$ink2", "width": 1}, "layer": "below",
                }
            )
        traces.append(
            {
                "type": "scatter", "mode": "markers", "name": "Réglage",
                "x": [moment.strftime(TIME_FORMAT) for moment in moments],
                "y": [top] * len(moments),
                "text": ["<br>".join(grouped[moment]) for moment in moments],
                "xaxis": "x", "yaxis": "y3",
                "marker": {"symbol": "diamond", "size": 10, "color": "$ink", "line": {"color": "$surface", "width": 2}},
                "hovertemplate": "%{text}<extra></extra>",
            }
        )

    layout = {
        "paper_bgcolor": "$surface",
        "plot_bgcolor": "$surface",
        "font": {"family": FONT, "color": "$ink2", "size": 12},
        "margin": {"l": 64, "r": 16, "t": 72, "b": 40},
        "hovermode": "x unified",
        "hoverlabel": {"bgcolor": "$surface", "bordercolor": "$axis", "font": {"color": "$ink", "size": 12}},
        "legend": {"orientation": "h", "x": 0, "y": 1.07, "yanchor": "bottom", "font": {"color": "$ink2"}},
        "dragmode": "zoom",
        "xaxis": _axis(
            type="date", anchor="y", domain=[0, 1], showspikes=True, spikemode="across",
            spikesnap="cursor", spikethickness=1, spikecolor="$muted", spikedash="solid",
        ),
        "yaxis": _axis(domain=[0.0, 0.16], anchor="x", title=_title("État"), rangemode="tozero", nticks=3),
        "yaxis2": _axis(domain=[0.24, 0.44], anchor="x", title=_title("O₂ %"), rangemode="tozero", nticks=4),
        "yaxis3": _axis(domain=[0.52, 1.0], anchor="x", title=_title("°C"), nticks=6),
        "shapes": shapes,
        "annotations": annotations,
    }
    return {"data": traces, "layout": layout, "config": CONFIG}


def build_startups_spec(
    readings: pd.DataFrame,
    startups: list[pd.Timestamp],
    episodes: list[ErrorEpisode],
    metric: str,
    window_min: float,
    visible: tuple | None = None,
) -> dict:
    """Every startup drawn from its own t = 0, so tuning changes can be compared.

    `startups` is the full list (needed to stop a window at the next startup);
    `visible` = (start, end) keeps only the startups inside that period.
    Colour is a one-hue ramp from the oldest (receding) to the latest startup (drawn
    thicker). Defects are marked with a cross at the moment they started.
    """
    label, unit, fmt = METRICS[metric]
    shown = [s for s in startups if visible is None or visible[0] <= s < visible[1]]
    shown_set = set(shown)
    traces = []
    for rank, start in enumerate(shown):
        position = bisect.bisect_left(startups, start)  # index in the full list
        end = start + timedelta(minutes=window_min)
        if position + 1 < len(startups):
            end = min(end, startups[position + 1])
        part = between(readings, start, end).dropna(subset=[metric])
        if part.empty:
            continue
        bucket = round(rank * 5 / max(len(shown) - 1, 1))
        is_latest = rank == len(shown) - 1
        suffix = f" {unit}" if unit else ""
        traces.append(
            {
                "type": "scatter", "mode": "lines", "name": f"{start:%d.%m %H:%M}", "showlegend": False,
                "x": [round((moment - start).total_seconds() / 60, 2) for moment in part["timestamp"]],
                "y": _values(part, metric),
                "line": {"color": f"$ramp{bucket}", "width": 3 if is_latest else 1.5},
                "hovertemplate": f"{start:%d.%m %H:%M} · +%{{x:.0f}} min · %{{y:{fmt}}}{suffix}<extra></extra>",
            }
        )

    values = dict(zip(readings["timestamp"], readings[metric]))
    cross_x, cross_y, cross_text = [], [], []
    for episode in episodes:
        position = bisect.bisect_right(startups, episode.start) - 1
        if position < 0 or startups[position] not in shown_set:
            continue
        minutes = (episode.start - startups[position]).total_seconds() / 60
        value = _number(values.get(episode.start))
        if minutes > window_min or value is None:
            continue
        cross_x.append(round(minutes, 2))
        cross_y.append(value)
        cross_text.append(f"Défaut {episode.code} · {episode.start:%d.%m %H:%M} · +{minutes:.0f} min")
    if cross_x:
        traces.append(
            {
                "type": "scatter", "mode": "markers", "name": "Défaut", "showlegend": True,
                "x": cross_x, "y": cross_y, "text": cross_text,
                "marker": {"symbol": "x", "size": 10, "color": "$critical", "line": {"color": "$surface", "width": 2}},
                "hovertemplate": "%{text}<extra></extra>",
            }
        )
    if not traces:
        return _empty_spec("Aucun démarrage sur cette période")

    title = f"{label} ({unit})" if unit else label
    layout = {
        "paper_bgcolor": "$surface",
        "plot_bgcolor": "$surface",
        "font": {"family": FONT, "color": "$ink2", "size": 12},
        "margin": {"l": 64, "r": 16, "t": 40, "b": 56},
        "hovermode": "closest",
        "hoverdistance": 24,
        "hoverlabel": {"bgcolor": "$surface", "bordercolor": "$axis", "font": {"color": "$ink", "size": 12}},
        "legend": {"orientation": "h", "x": 0, "y": 1.06, "yanchor": "bottom", "font": {"color": "$ink2"}},
        "xaxis": _axis(title=_title("minutes depuis le démarrage"), rangemode="tozero"),
        "yaxis": _axis(title=_title(title)),
    }
    return {"data": traces, "layout": layout, "config": CONFIG}
