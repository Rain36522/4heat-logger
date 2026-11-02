"""Pages of the app. Business rules live in monitor.core; views only gather and render."""

import statistics
from collections import defaultdict
from datetime import datetime, time, timedelta
from functools import lru_cache

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import cache_control

from .core import charts
from .core import readings as rd
from .forms import SettingChangeForm
from .models import CodeLabel, Parameter, SettingChange

METRIC_CHOICES = [(key, label) for key, (label, _unit, _fmt) in charts.METRICS.items()]


# --- helpers -----------------------------------------------------------------------


def _load_readings():
    return rd.load_readings(settings.HEATING_CSV_PATH)


def _parse_day(text):
    try:
        return datetime.strptime(text or "", "%Y-%m-%d").date()
    except ValueError:
        return None


def _bounded_int(text, default, low, high):
    try:
        return max(low, min(high, int(text)))
    except (TypeError, ValueError):
        return default


def _day_range(request, readings, default_days):
    """Read ?from=&to= (YYYY-MM-DD). Without them: the last `default_days` days with data (None = all)."""
    if readings.empty:
        first_day = last_day = datetime.now().date()
    else:
        first_day = readings["timestamp"].iloc[0].date()
        last_day = readings["timestamp"].iloc[-1].date()
    to_day = _parse_day(request.GET.get("to")) or last_day
    default_from = first_day if default_days is None else to_day - timedelta(days=default_days - 1)
    from_day = _parse_day(request.GET.get("from")) or default_from
    if from_day > to_day:
        from_day, to_day = to_day, from_day
    return {
        "start": datetime.combine(from_day, time.min),
        "end": datetime.combine(to_day, time.min) + timedelta(days=1),
        "from": from_day.isoformat(),
        "to": to_day.isoformat(),
        "presets": [
            {"label": "Dernier jour", "from": last_day.isoformat(), "to": last_day.isoformat()},
            {"label": "3 jours", "from": (last_day - timedelta(days=2)).isoformat(), "to": last_day.isoformat()},
            {"label": "7 jours", "from": (last_day - timedelta(days=6)).isoformat(), "to": last_day.isoformat()},
            {"label": "Tout", "from": first_day.isoformat(), "to": last_day.isoformat()},
        ],
    }


def _changes_between(start, end):
    changes = list(
        SettingChange.objects.filter(timestamp__gte=start, timestamp__lt=end)
        .select_related("parameter")
        .order_by("timestamp", "id")
    )
    marks = [(change.timestamp, f"{change.parameter.code}: {change.old_value or '∅'} → {change.new_value}") for change in changes]
    return changes, marks


def _show(value, decimals=0):
    """Number as text, with a dash for a missing reading (None or NaN)."""
    return "–" if value is None or value != value else f"{value:.{decimals}f}"


def _age_text(seconds):
    minutes = int(seconds // 60)
    if minutes < 1:
        return "à l'instant"
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 24 * 60:
        return f"{minutes // 60} h {minutes % 60:02d}"
    return f"{minutes // (24 * 60)} j"


# --- pages -------------------------------------------------------------------------


def status(request):
    readings = _load_readings()
    context = {"has_data": not readings.empty}
    if readings.empty:
        return render(request, "monitor/status.html", context)

    state_names = CodeLabel.labels(CodeLabel.Kind.STATE)
    error_names = CodeLabel.labels(CodeLabel.Kind.ERROR)
    last_stamp = readings["timestamp"].iloc[-1]
    age_s = (datetime.now() - last_stamp.to_pydatetime()).total_seconds()

    def latest(column):
        return rd.last_valid(readings, column)[0]

    state, error = latest("state"), latest("error")
    state = None if state is None else int(state)
    error = None if error is None else int(error)

    startup_times = rd.find_startups(readings)
    window = rd.between(readings, last_stamp - timedelta(hours=3), last_stamp + timedelta(seconds=1))
    week = rd.between(readings, last_stamp - timedelta(days=7), last_stamp + timedelta(seconds=1))
    week_episodes = rd.error_episodes(week, startup_times)
    _, marks = _changes_between(last_stamp - timedelta(hours=3), last_stamp + timedelta(seconds=1))
    spec = charts.build_timeline_spec(window, rd.error_episodes(window, startup_times), marks, state_names)

    recent_rows = [
        {
            "time": row.timestamp,
            "state": _show(row.state),
            "error": _show(row.error),
            "boiler": _show(row.boiler_temp),
            "target": _show(row.boiler_target_temp),
            "exhaust": _show(row.exhaust_temp),
            "oxygen": _show(row.oxygen_percent, 1),
        }
        for row in readings.tail(8).iloc[::-1].itertuples(index=False)
    ]
    context.update(
        live=age_s <= settings.STATUS_LIVE_MAX_AGE_S,
        last_stamp=last_stamp.to_pydatetime(),
        age_text=_age_text(age_s),
        state=state,
        state_name=state_names.get(state, ""),
        error=error,
        error_name=error_names.get(error, ""),
        metrics=[
            {"label": "Chaudière", "value": _show(latest("boiler_temp")), "unit": "°C"},
            {"label": "Consigne", "value": _show(latest("boiler_target_temp")), "unit": "°C"},
            {"label": "Fumées", "value": _show(latest("exhaust_temp")), "unit": "°C"},
            {"label": "O₂", "value": _show(latest("oxygen_percent"), 1), "unit": "%"},
        ],
        week_defect_count=len(week_episodes),
        last_defects=list(reversed(week_episodes))[:3],
        recent_rows=recent_rows,
        recent_changes=SettingChange.objects.select_related("parameter")[:5],
        figure=spec,
        chart_label="Dernières 3 heures : températures, O₂ et état",
    )
    return render(request, "monitor/status.html", context)


def timeline(request):
    readings = _load_readings()
    day = _day_range(request, readings, default_days=1)
    window = rd.between(readings, day["start"], day["end"])
    episodes = rd.error_episodes(window, rd.find_startups(readings))
    changes, marks = _changes_between(day["start"], day["end"])
    spec = charts.build_timeline_spec(window, episodes, marks, CodeLabel.labels(CodeLabel.Kind.STATE))
    return render(
        request,
        "monitor/timeline.html",
        {
            "day": day,
            "figure": spec,
            "chart_label": "Températures, O₂ et état sur la période choisie",
            "episodes": list(reversed(episodes)),
            "changes": changes,
            "readings_count": len(window),
        },
    )


def startups(request):
    readings = _load_readings()
    day = _day_range(request, readings, default_days=None)
    metric = request.GET.get("metric", "boiler_temp")
    if metric not in charts.METRICS:
        metric = "boiler_temp"
    window_min = _bounded_int(request.GET.get("window"), 45, 5, 240)
    min_gap = _bounded_int(request.GET.get("min_gap"), 30, 5, 600)

    all_startups = rd.find_startups(readings, min_gap_s=min_gap * 60)
    episodes = rd.error_episodes(readings, all_startups)
    shown = [s for s in all_startups if day["start"] <= s < day["end"]]
    spec = charts.build_startups_spec(
        readings, all_startups, episodes, metric, window_min, visible=(day["start"], day["end"])
    )
    return render(
        request,
        "monitor/startups.html",
        {
            "day": day,
            "figure": spec,
            "chart_label": "Démarrages superposés, alignés sur leur début",
            "metric": metric,
            "metric_choices": METRIC_CHOICES,
            "window_min": window_min,
            "min_gap": min_gap,
            "startup_count": len(shown),
        },
    )


def faults(request):
    readings = _load_readings()
    day = _day_range(request, readings, default_days=None)
    window = rd.between(readings, day["start"], day["end"])
    episodes = rd.error_episodes(window, rd.find_startups(readings))
    error_names = CodeLabel.labels(CodeLabel.Kind.ERROR)
    state_names = CodeLabel.labels(CodeLabel.Kind.STATE)

    by_code = defaultdict(list)
    for episode in episodes:
        by_code[episode.code].append(episode)
    summary = []
    for code, group in sorted(by_code.items()):
        after_startup = [e.minutes_since_startup for e in group if e.minutes_since_startup is not None]
        summary.append(
            {
                "code": code,
                "name": error_names.get(code, ""),
                "count": len(group),
                "median_duration": statistics.median(e.duration_min for e in group),
                "median_after_startup": statistics.median(after_startup) if after_startup else None,
            }
        )
    rows = [
        {"episode": e, "error_name": error_names.get(e.code, ""), "state_name": state_names.get(e.state, "")}
        for e in reversed(episodes)
    ]
    return render(request, "monitor/faults.html", {"day": day, "summary": summary, "rows": rows, "total": len(episodes)})


def journal(request):
    if request.method == "POST":
        form = SettingChangeForm(request.POST)
        if form.is_valid():
            change = form.save()
            messages.success(request, f"Enregistré : {change}")
            return redirect("journal")
    else:
        form = SettingChangeForm()
    return render(
        request,
        "monitor/journal.html",
        {
            "form": form,
            "parameters": Parameter.objects.all(),
            "changes": SettingChange.objects.select_related("parameter")[:40],
        },
    )


def parameter_info(request, code):
    """JSON used by the journal form to show the legend and the current value of a parameter."""
    parameter = Parameter.objects.filter(code__iexact=code.strip()).first()
    if parameter is None:
        return JsonResponse({"error": "unknown parameter"}, status=404)
    return JsonResponse(
        {
            "code": parameter.code,
            "section": parameter.section,
            "description": parameter.description,
            "unit": parameter.unit,
            "state": parameter.state_label,
            "current_value": parameter.current_value,
        }
    )


@lru_cache(maxsize=1)
def _plotly_js() -> str:
    from plotly.offline import get_plotlyjs  # imported here: only this view needs the package

    return get_plotlyjs()


@cache_control(max_age=86400, public=True)
def plotly_js(request):
    """Serve Plotly.js from the installed Python package: no CDN, always the matching version."""
    return HttpResponse(_plotly_js(), content_type="text/javascript")
