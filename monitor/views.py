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

from .core import boiler_cycle as boiler_cycle_data
from .core import charts
from .core import readings as rd
from .core.exports import CSV_CONTENT_TYPE, as_number, build_csv
from .forms import SettingChangeForm
from .models import CodeLabel, Parameter, SettingChange

METRIC_CHOICES = [(key, label) for key, (label, _unit, _fmt) in charts.METRICS.items()]

# Column titles of the readings export, in the order of rd.VALUE_COLUMNS.
READING_HEADERS = {
    "state": "État",
    "error": "Défaut",
    "exhaust_temp": "Fumées (°C)",
    "boiler_temp": "Chaudière (°C)",
    "oxygen_percent": "O₂ (%)",
    "boiler_target_temp": "Consigne (°C)",
    "thermostat_temp": "Thermostat (°C)",
}
NO_SECTION = "Sans section"


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


def _csv_response(content: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type=CSV_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _change_rows(changes):
    for change in changes:
        yield (
            change.timestamp,
            "oui" if change.time_is_approximate else "",
            change.parameter.code,
            change.parameter.section,
            as_number(change.old_value),
            as_number(change.new_value),
            change.comment,
        )


CHANGE_HEADERS = ["Date", "Heure approx.", "Paramètre", "Section", "Ancienne valeur", "Nouvelle valeur", "Commentaire"]


def _parameter_rows():
    """Every parameter with its current value, ready for the list page and the export."""
    rows = []
    for parameter in Parameter.objects.prefetch_related("changes"):
        changes = list(parameter.changes.all())  # prefetched: no query per parameter
        current = parameter.current_value
        rows.append(
            {
                "code": parameter.code,
                "section": parameter.section or NO_SECTION,
                "description": parameter.description,
                "unit": parameter.unit,
                "state_label": parameter.state_label,
                "baseline": parameter.baseline_value,
                "current": current,
                "modified": current != parameter.baseline_value,
                "change_count": len(changes),
                "last_change": max((change.timestamp for change in changes), default=None),
            }
        )
    return rows


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
            {"label": "Thermostat", "value": _show(latest("thermostat_temp")), "unit": "°C"},
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


def timeline_export(request):
    """The readings behind the Graphes page for the same period, as a CSV file."""
    readings = _load_readings()
    day = _day_range(request, readings, default_days=1)
    window = rd.between(readings, day["start"], day["end"])
    content = build_csv(
        ["Date", *(READING_HEADERS[column] for column in rd.VALUE_COLUMNS)],
        window[["timestamp", *rd.VALUE_COLUMNS]].itertuples(index=False, name=None),
    )
    return _csv_response(content, f"graphe_{day['from']}_{day['to']}.csv")


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


MAX_COMPARED_DAYS = 8
MAX_SHIFT_MIN = 720


def compare_days(request):
    """Several chosen days on one 00:00–24:00 axis, each with its own time shift."""
    readings = _load_readings()
    metric = request.GET.get("metric", "boiler_temp")
    if metric not in charts.METRICS:
        metric = "boiler_temp"

    shifts = request.GET.getlist("shift")
    chosen = {}
    for index, text in enumerate(request.GET.getlist("day")):
        day = _parse_day(text)
        if day is not None and day not in chosen:
            shift = shifts[index] if index < len(shifts) else None
            chosen[day] = _bounded_int(shift, 0, -MAX_SHIFT_MIN, MAX_SHIFT_MIN)
    if not chosen and not readings.empty:
        # First visit: the last three days with data, not shifted.
        chosen = {day: 0 for day in sorted(set(readings["timestamp"].dt.date))[-3:]}
    days = sorted(chosen.items())[:MAX_COMPARED_DAYS]

    changes = []
    if days:
        first, last = days[0][0], days[-1][0]
        changes, _ = _changes_between(
            datetime.combine(first, time.min), datetime.combine(last, time.min) + timedelta(days=1)
        )
    return render(
        request,
        "monitor/compare_days.html",
        {
            "figure": charts.build_days_spec(readings, days, metric),
            "chart_label": "Jours choisis superposés sur une même journée",
            "days": [{"date": day.isoformat(), "label": charts.day_label(day), "shift": shift} for day, shift in days],
            "can_add": len(days) < MAX_COMPARED_DAYS,
            "max_shift": MAX_SHIFT_MIN,
            "metric": metric,
            "metric_choices": METRIC_CHOICES,
            "changes": changes,
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


def parameters(request):
    rows = _parameter_rows()
    sections = defaultdict(list)
    for row in rows:
        sections[row["section"]].append(row)
    ordered = sorted(sections.items(), key=lambda item: (item[0] == NO_SECTION, item[0].lower()))
    return render(
        request,
        "monitor/parameters.html",
        {
            "sections": ordered,
            "total": len(rows),
            "modified_count": sum(row["modified"] for row in rows),
        },
    )


def boiler_cycle(request):
    """Read-only explanation of the boiler cycle, with the current parameter values."""
    readings = _load_readings()
    live = {}
    if not readings.empty:
        live = {key: rd.last_valid(readings, column)[0] for key, column in
                (("oxygen", "oxygen_percent"), ("exhaust", "exhaust_temp"), ("boiler", "boiler_temp"), ("state", "state"))}
        live["time"] = readings["timestamp"].iloc[-1].strftime("%d.%m.%Y %H:%M")
    return render(
        request,
        "monitor/boiler_cycle.html",
        {"cycle": boiler_cycle_data.build_payload(_parameter_rows(), live)},
    )


def parameters_export(request):
    content = build_csv(
        ["Code", "Section", "Description", "Unité", "État concerné", "Valeur de base",
         "Valeur actuelle", "Modifié", "Nb changements", "Dernier changement"],
        (
            (
                row["code"],
                row["section"],
                row["description"],
                row["unit"],
                row["state_label"],
                as_number(row["baseline"]),
                as_number(row["current"]),
                "oui" if row["modified"] else "",
                row["change_count"],
                row["last_change"],
            )
            for row in _parameter_rows()
        ),
    )
    return _csv_response(content, f"parametres_{datetime.now():%Y-%m-%d}.csv")


def changes_export(request):
    changes = SettingChange.objects.select_related("parameter").order_by("timestamp", "id")
    content = build_csv(CHANGE_HEADERS, _change_rows(changes))
    return _csv_response(content, f"historique_reglages_{datetime.now():%Y-%m-%d}.csv")


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
