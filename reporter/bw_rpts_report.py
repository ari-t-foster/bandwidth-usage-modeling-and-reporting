#!/usr/bin/env python3
"""Build, score, render, and optionally print the bandwidth usage report."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


DATA_TYPE_VERSION = 2
GB = 1_000_000_000.0
LETTER_W = 612.0
LETTER_H = 792.0


@dataclass
class SourceRow:
    label: str
    year: int
    month: int
    day: int | None
    rx: int
    tx: int

    @property
    def total(self) -> int:
        return self.rx + self.tx

    @property
    def sort_key(self) -> tuple[int, int, int]:
        return (self.year, self.month, self.day or 0)


@dataclass
class ReportRow:
    label: str
    values: dict[str, Any]


def utc_now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def bytes_to_gb(value: int | float) -> float:
    return float(value) / GB


def ratio_down_up(rx: int, tx: int) -> float | None:
    if tx <= 0:
        return None
    return float(rx) / float(tx)


def month_index(year: int, month: int) -> int:
    return year * 12 + month


def latest_file(input_dir: Path, patterns: list[str]) -> Path | None:
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(p for p in input_dir.glob(pattern) if p.is_file())
    if not candidates:
        return None
    return max(candidates, key=lambda p: (p.stat().st_mtime, p.name))


def parse_size_to_bytes(value: str) -> int:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)\s*", value or "")
    if not match:
        raise ValueError(f"cannot parse size: {value!r}")

    amount = float(match.group(1))
    unit = match.group(2)
    multipliers = {
        "B": 1,
        "KB": 1_000,
        "MB": 1_000_000,
        "GB": 1_000_000_000,
        "TB": 1_000_000_000_000,
        "KiB": 1024,
        "MiB": 1024**2,
        "GiB": 1024**3,
        "TiB": 1024**4,
    }
    if unit not in multipliers:
        raise ValueError(f"unsupported size unit: {unit!r}")
    return int(round(amount * multipliers[unit]))


def parse_vnstat_json(path: Path, daily: bool) -> list[SourceRow]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} is not a vnstat row list")

    rows: list[SourceRow] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        item_date = item.get("date", {})
        year = int(item_date["year"])
        month = int(item_date["month"])
        day = int(item_date["day"]) if daily else None
        label = f"{year:04d}-{month:02d}-{day:02d}" if daily else f"{year:04d}/{month:02d}"
        rows.append(
            SourceRow(
                label=label,
                year=year,
                month=month,
                day=day,
                rx=int(item.get("rx", 0)),
                tx=int(item.get("tx", 0)),
            )
        )
    return sorted(rows, key=lambda row: row.sort_key)


def parse_vnstat_csv(path: Path, daily: bool) -> list[SourceRow]:
    rows: list[SourceRow] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for item in reader:
            time_value = (item.get("Time") or "").strip()
            rx = parse_size_to_bytes(item.get("WAN RX") or "0 B")
            tx = parse_size_to_bytes(item.get("WAN TX") or "0 B")

            if daily:
                parsed = datetime.strptime(time_value, "%Y-%m-%d").date()
                label = parsed.isoformat()
                day: int | None = parsed.day
            else:
                parsed_dt = datetime.strptime(time_value, "%m/%Y")
                parsed = date(parsed_dt.year, parsed_dt.month, 1)
                label = f"{parsed.year:04d}/{parsed.month:02d}"
                day = None

            rows.append(SourceRow(label, parsed.year, parsed.month, day, rx, tx))
    return sorted(rows, key=lambda row: row.sort_key)


def load_source_rows(input_dir: Path, kind: str, daily: bool) -> tuple[Path, list[SourceRow]]:
    json_patterns = [f"{kind}.vnstat.*.json", f"{kind}.vnstat.json"]
    csv_patterns = [f"{kind}.vnstat.*.csv", f"{kind}.vnstat.csv", f"vnstat.{kind}.csv"]
    path = latest_file(input_dir, json_patterns)
    if path is not None:
        return path, parse_vnstat_json(path, daily=daily)

    path = latest_file(input_dir, csv_patterns)
    if path is not None:
        return path, parse_vnstat_csv(path, daily=daily)

    raise FileNotFoundError(f"no {kind} vnstat JSON or CSV file found in {input_dir}")


def infer_report_date(daily_rows: list[SourceRow]) -> date:
    dated = [date(row.year, row.month, row.day) for row in daily_rows if row.day is not None]
    if dated:
        return max(dated)
    return datetime.now(timezone.utc).date()


def build_bandwidth_usage(
    monthly_rows: list[SourceRow],
    daily_rows: list[SourceRow],
    report_day: date,
    previous_months: int,
    include_zero_days: bool,
    include_zero_months: bool,
) -> dict[str, Any]:
    current_month_index = month_index(report_day.year, report_day.month)
    prior_months = [
        row
        for row in monthly_rows
        if month_index(row.year, row.month) < current_month_index
        and (include_zero_months or row.total > 0)
    ][-previous_months:]

    data_points: list[dict[str, dict[str, Any]]] = []
    for row in prior_months:
        data_points.append(
            {
                row.label: {
                    "year": row.year,
                    "gb_up": bytes_to_gb(row.tx),
                    "gb_down": bytes_to_gb(row.rx),
                    "gb_total": bytes_to_gb(row.total),
                    "d_u_ratio": ratio_down_up(row.rx, row.tx),
                }
            }
        )

    mtd_rx = 0
    mtd_tx = 0
    for row in sorted(daily_rows, key=lambda item: item.sort_key):
        if row.day is None:
            continue
        row_day = date(row.year, row.month, row.day)
        if row_day.year != report_day.year or row_day.month != report_day.month:
            continue
        if row_day > report_day:
            continue

        mtd_rx += row.rx
        mtd_tx += row.tx
        mtd_total = mtd_rx + mtd_tx
        if not include_zero_days and mtd_total <= 0:
            continue

        data_points.append(
            {
                row.label: {
                    "year": row.year,
                    "gb_up": bytes_to_gb(mtd_tx),
                    "gb_down": bytes_to_gb(mtd_rx),
                    "gb_total": bytes_to_gb(mtd_total),
                    "d_u_ratio": ratio_down_up(mtd_rx, mtd_tx),
                }
            }
        )

    return {
        "data_type": "bandwidth_usage",
        "data_type_version": DATA_TYPE_VERSION,
        "data_points": data_points,
        "data_when": utc_now_rfc3339(),
        "response": None,
        "response_when": None,
    }


def write_json_atomic(path: Path, data: dict[str, Any], mode: int = 0o644) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        mode = path.stat().st_mode
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(data, tmp, indent=2, sort_keys=False)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.chmod(tmp_path, mode)
    os.replace(tmp_path, path)


def score_bandwidth_usage(json_path: Path, scorer_path: Path) -> None:
    if not scorer_path.exists():
        raise FileNotFoundError(f"scorer not found: {scorer_path}")
    subprocess.run([sys.executable, str(scorer_path), str(json_path)], check=True)


def iter_labeled_points(points: Any):
    if isinstance(points, list):
        for item in points:
            if isinstance(item, dict) and len(item) == 1:
                label, values = next(iter(item.items()))
                if isinstance(values, dict):
                    yield str(label), values
    elif isinstance(points, dict):
        for label, values in points.items():
            if isinstance(values, dict):
                yield str(label), values


def load_report_rows(json_path: Path) -> tuple[dict[str, Any], list[ReportRow]]:
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    by_label: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for label, values in iter_labeled_points(data.get("data_points", [])):
        by_label[label] = dict(values)
        order.append(label)

    response = data.get("response") or {}
    for label, values in iter_labeled_points(response.get("data_points", [])):
        by_label.setdefault(label, {}).update(values)

    return data, [ReportRow(label, by_label[label]) for label in order if label in by_label]


def ps_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def ps_text(
    out: list[str],
    x: float,
    y: float,
    text: Any,
    size: float = 6.0,
    font: str = "Helvetica",
    align: str = "left",
    angle: float = 0.0,
) -> None:
    out.append("gsave")
    out.append(f"{x:.2f} {y:.2f} translate")
    if angle:
        out.append(f"{angle:.2f} rotate")
    out.append(f"/{font} findfont {size:.2f} scalefont setfont")
    escaped = ps_escape(text)
    if align == "right":
        out.append(f"({escaped}) dup stringwidth pop neg 0 moveto show")
    elif align == "center":
        out.append(f"({escaped}) dup stringwidth pop -2 div 0 moveto show")
    else:
        out.append(f"0 0 moveto ({escaped}) show")
    out.append("grestore")


def ps_line(out: list[str], x1: float, y1: float, x2: float, y2: float) -> None:
    out.append(f"newpath {x1:.2f} {y1:.2f} moveto {x2:.2f} {y2:.2f} lineto stroke")


def ps_rect_path(x: float, y: float, w: float, h: float) -> str:
    return (
        f"newpath {x:.2f} {y:.2f} moveto {w:.2f} 0 rlineto "
        f"0 {h:.2f} rlineto {-w:.2f} 0 rlineto closepath"
    )


def ps_rect_fill(out: list[str], x: float, y: float, w: float, h: float, gray: float) -> None:
    if w <= 0 or h <= 0:
        return
    out.append("gsave")
    out.append(f"{gray:.3f} setgray")
    out.append(f"{ps_rect_path(x, y, w, h)} fill")
    out.append("grestore")


def ps_rect_stroke(out: list[str], x: float, y: float, w: float, h: float) -> None:
    if w <= 0 or h <= 0:
        return
    out.append(f"{ps_rect_path(x, y, w, h)} stroke")


def ps_hatch_rect(out: list[str], x: float, y: float, w: float, h: float, spacing: float = 3.0) -> None:
    if w <= 0 or h <= 0:
        return
    ps_rect_fill(out, x, y, w, h, 1.0)
    out.append("gsave")
    out.append(ps_rect_path(x, y, w, h))
    out.append("clip")
    out.append("0 setgray 0.30 setlinewidth")
    start = x - h - spacing
    stop = x + w + spacing
    k = start
    while k <= stop:
        ps_line(out, k, y, k + h, y + h)
        k += spacing
    out.append("grestore")
    ps_rect_stroke(out, x, y, w, h)


def ps_marker(out: list[str], x: float, y: float, kind: str, size: float = 2.6) -> None:
    r = size
    if kind == "circle":
        out.append(f"newpath {x:.2f} {y:.2f} {r:.2f} 0 360 arc closepath fill")
    elif kind == "square":
        out.append(ps_rect_path(x - r, y - r, 2 * r, 2 * r) + " fill")
    elif kind == "triangle":
        out.append(
            f"newpath {x:.2f} {y + r:.2f} moveto "
            f"{x - r:.2f} {y - r:.2f} lineto {x + r:.2f} {y - r:.2f} lineto "
            "closepath fill"
        )
    else:
        out.append(f"newpath {x:.2f} {y:.2f} {r:.2f} 0 360 arc closepath stroke")


def nice_ceiling(value: float) -> float:
    if value <= 0 or not math.isfinite(value):
        return 1.0
    exponent = math.floor(math.log10(value))
    base = 10 ** exponent
    fraction = value / base
    for step in (1, 2, 5, 10):
        if fraction <= step:
            return float(step * base)
    return float(10 * base)


def linear_ticks(y_max: float, count: int = 4) -> list[float]:
    if y_max <= 0:
        return [0.0, 1.0]
    return [y_max * i / count for i in range(count + 1)]


def fmt_axis(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value / 1000:.0f}k"
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.0f}"
    if abs(value) >= 1:
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{value:.2f}".rstrip("0").rstrip(".")


def fmt_gb(value: Any) -> str:
    if value is None:
        return ""
    value = float(value)
    if abs(value) < 10:
        return f"{value:.2f}"
    if abs(value) < 100:
        return f"{value:.1f}"
    return f"{value:.0f}"


def fmt_ratio(value: Any) -> str:
    if value is None:
        return ""
    value = float(value)
    if value >= 100:
        return f"{value:.0f}"
    return f"{value:.1f}"


def fmt_prob(value: Any) -> str:
    if value is None:
        return ""
    return f"{float(value):.3f}"


def fmt_n(value: Any) -> str:
    if value is None:
        return ""
    value = float(value)
    if value < 10:
        return f"{value:.2f}"
    if value < 100:
        return f"{value:.1f}"
    if value < 1000:
        return f"{value:.0f}"
    if value < 1_000_000:
        return f"{value / 1000:.1f}k"
    return f"{value / 1_000_000:.1f}M"


def short_label(label: str) -> str:
    date_match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", label)
    if date_match:
        return f"{int(date_match.group(2))}/{int(date_match.group(3))}"
    month_match = re.fullmatch(r"(\d{4})/(\d{2})", label)
    if month_match:
        return f"{int(month_match.group(2))}/{month_match.group(1)[2:]}"
    return label


def chart_area(x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    return x + 34, y + 20, w - 46, h - 38


def draw_chart_frame(
    out: list[str],
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    rows: list[ReportRow],
    y_ticks: list[float],
    y_to_plot: Any,
    y_label: Any = fmt_axis,
) -> tuple[list[float], float, float, float, float]:
    ps_text(out, x + 2, y + h - 10, title, size=7.0, font="Helvetica-Bold")
    px, py, pw, ph = chart_area(x, y, w, h)
    out.append("0 setgray 0.35 setlinewidth [] 0 setdash")
    ps_rect_stroke(out, px, py, pw, ph)

    for tick in y_ticks:
        ty = y_to_plot(tick)
        out.append("0.86 setgray 0.20 setlinewidth")
        ps_line(out, px, ty, px + pw, ty)
        out.append("0 setgray 0.30 setlinewidth")
        ps_text(out, px - 4, ty - 2, y_label(tick), size=4.8, align="right")

    n = len(rows)
    if n <= 1:
        xs = [px + pw / 2]
    else:
        xs = [px + (pw * idx / (n - 1)) for idx in range(n)]

    stride = max(1, math.ceil(max(n, 1) / 24))
    for idx, row in enumerate(rows):
        if idx % stride == 0 or idx == n - 1:
            ps_text(out, xs[idx], py - 8, short_label(row.label), size=4.6, align="center")
            out.append("0 setgray 0.25 setlinewidth")
            ps_line(out, xs[idx], py, xs[idx], py - 2)

    return xs, px, py, pw, ph


def draw_usage_chart(out: list[str], rows: list[ReportRow], x: float, y: float, w: float, h: float) -> None:
    max_total = max((float(row.values.get("gb_total") or 0) for row in rows), default=1.0)
    y_max = nice_ceiling(max_total * 1.08)

    def y_to_plot(value: float) -> float:
        _, py, _, ph = chart_area(x, y, w, h)
        return py + (value / y_max) * ph

    xs, px, py, pw, ph = draw_chart_frame(
        out, x, y, w, h, "Usage GB, stacked up/down with total", rows, linear_ticks(y_max), y_to_plot
    )

    step = pw / max(len(rows), 1)
    bar_w = min(9.0, step * 0.62)
    total_points: list[tuple[float, float]] = []
    for idx, row in enumerate(rows):
        gb_down = float(row.values.get("gb_down") or 0)
        gb_up = float(row.values.get("gb_up") or 0)
        gb_total = float(row.values.get("gb_total") or 0)
        x0 = xs[idx] - bar_w / 2
        down_h = max(0.0, y_to_plot(gb_down) - py)
        up_h = max(0.0, y_to_plot(gb_down + gb_up) - y_to_plot(gb_down))
        ps_rect_fill(out, x0, py, bar_w, down_h, 0.86)
        ps_rect_stroke(out, x0, py, bar_w, down_h)
        ps_hatch_rect(out, x0, py + down_h, bar_w, up_h)
        total_points.append((xs[idx], y_to_plot(gb_total)))

    draw_polyline(out, total_points, dash=None, marker="circle", width=0.7)
    draw_usage_legend(out, x + w - 142, y + h - 14)


def draw_usage_legend(out: list[str], x: float, y: float) -> None:
    ps_rect_fill(out, x, y - 2, 8, 5, 0.86)
    ps_rect_stroke(out, x, y - 2, 8, 5)
    ps_text(out, x + 11, y - 1, "down", size=5.0)
    ps_hatch_rect(out, x + 43, y - 2, 8, 5, spacing=2.0)
    ps_text(out, x + 54, y - 1, "up", size=5.0)
    out.append("0 setgray 0.6 setlinewidth [] 0 setdash")
    ps_line(out, x + 76, y, x + 91, y)
    ps_marker(out, x + 83.5, y, "circle", size=1.8)
    ps_text(out, x + 95, y - 1, "total", size=5.0)


def draw_polyline(
    out: list[str],
    points: list[tuple[float, float] | None],
    dash: str | None,
    marker: str,
    width: float = 0.5,
) -> None:
    if not points:
        return
    dash_cmd = dash if dash is not None else "[] 0"
    out.append(f"0 setgray {width:.2f} setlinewidth {dash_cmd} setdash")
    current: list[tuple[float, float]] = []
    for point in points + [None]:
        if point is None:
            if current:
                out.append("newpath")
                out.append(f"{current[0][0]:.2f} {current[0][1]:.2f} moveto")
                for px, py in current[1:]:
                    out.append(f"{px:.2f} {py:.2f} lineto")
                out.append("stroke")
            current = []
        else:
            current.append(point)
    out.append("[] 0 setdash")
    for point in points:
        if point is not None:
            ps_marker(out, point[0], point[1], marker, size=2.1)


def draw_line_legend(out: list[str], x: float, y: float) -> None:
    entries = [
        ("up", "[1 2] 0", "triangle"),
        ("down", "[4 2] 0", "square"),
        ("total", "[] 0", "circle"),
    ]
    dx = 0.0
    for label, dash, marker in entries:
        out.append(f"0 setgray 0.45 setlinewidth {dash} setdash")
        ps_line(out, x + dx, y, x + dx + 14, y)
        out.append("[] 0 setdash")
        ps_marker(out, x + dx + 7, y, marker, size=1.8)
        ps_text(out, x + dx + 17, y - 1, label, size=5.0)
        dx += 45 if label != "total" else 0


def draw_probability_chart(out: list[str], rows: list[ReportRow], x: float, y: float, w: float, h: float) -> None:
    def y_to_plot(value: float) -> float:
        _, py, _, ph = chart_area(x, y, w, h)
        return py + max(0.0, min(1.0, value)) * ph

    xs, _, _, _, _ = draw_chart_frame(
        out,
        x,
        y,
        w,
        h,
        "Exceedance probability",
        rows,
        [0.0, 0.25, 0.50, 0.75, 1.0],
        y_to_plot,
        y_label=lambda value: f"{value * 100:.0f}%",
    )
    series_specs = [
        ("p_up", "[1 2] 0", "triangle"),
        ("p_down", "[4 2] 0", "square"),
        ("p_total", None, "circle"),
    ]
    for key, dash, marker in series_specs:
        points: list[tuple[float, float] | None] = []
        for idx, row in enumerate(rows):
            value = row.values.get(key)
            points.append(None if value is None else (xs[idx], y_to_plot(float(value))))
        draw_polyline(out, points, dash=dash, marker=marker)
    draw_line_legend(out, x + w - 142, y + h - 14)


def incidence_ticks(y_min: float, y_max: float, log_scale: bool) -> list[float]:
    if not log_scale:
        return linear_ticks(y_max, count=4)
    max_pow = int(math.ceil(math.log10(max(y_max, 1.0))))
    ticks = [1.0]
    for power in range(0, max_pow + 1):
        for mul in (2.0, 5.0, 10.0):
            value = mul * (10**power)
            if y_min <= value <= y_max * 1.0001:
                ticks.append(value)
    return sorted(set(ticks))


def draw_incidence_chart(out: list[str], rows: list[ReportRow], x: float, y: float, w: float, h: float) -> None:
    values = [
        float(row.values[key])
        for row in rows
        for key in ("inv_n_up", "inv_n_down", "inv_n_total")
        if row.values.get(key) is not None and float(row.values[key]) > 0
    ]
    max_n = max(values, default=2.0)
    min_n = max(1.0, min(values, default=1.0))
    log_scale = max_n > 20 and max_n / min_n > 8
    y_min = 1.0 if log_scale else 0.0
    y_max = nice_ceiling(max_n * 1.08)

    def y_to_plot(value: float) -> float:
        _, py, _, ph = chart_area(x, y, w, h)
        value = max(value, y_min if log_scale else 0.0)
        if log_scale:
            denom = math.log10(y_max) - math.log10(y_min)
            return py + ((math.log10(value) - math.log10(y_min)) / denom) * ph
        return py + (value / y_max) * ph

    title = "Incidence 1:n" + (" (log)" if log_scale else "")
    xs, _, _, _, _ = draw_chart_frame(
        out,
        x,
        y,
        w,
        h,
        title,
        rows,
        incidence_ticks(y_min, y_max, log_scale),
        y_to_plot,
        y_label=lambda value: "1:" + fmt_n(value),
    )
    series_specs = [
        ("inv_n_up", "[1 2] 0", "triangle"),
        ("inv_n_down", "[4 2] 0", "square"),
        ("inv_n_total", None, "circle"),
    ]
    for key, dash, marker in series_specs:
        points: list[tuple[float, float] | None] = []
        for idx, row in enumerate(rows):
            value = row.values.get(key)
            points.append(None if value is None else (xs[idx], y_to_plot(float(value))))
        draw_polyline(out, points, dash=dash, marker=marker)
    draw_line_legend(out, x + w - 142, y + h - 14)


def draw_table(out: list[str], rows: list[ReportRow], x: float, y: float, w: float, h: float) -> None:
    headers = ["date", "upGB", "downGB", "totGB", "D/U", "pUp", "pDn", "pTot", "nUp", "nDn", "nTot"]
    keys = [
        "label",
        "gb_up",
        "gb_down",
        "gb_total",
        "d_u_ratio",
        "p_up",
        "p_down",
        "p_total",
        "inv_n_up",
        "inv_n_down",
        "inv_n_total",
    ]
    widths = [62, 48, 52, 52, 38, 38, 38, 38, 50, 50, 50]
    total_w = sum(widths)
    if total_w > w:
        scale = w / total_w
        widths = [width * scale for width in widths]

    row_h = min(8.4, max(4.9, (h - 10) / max(len(rows) + 1, 1)))
    font_size = min(5.8, max(4.4, row_h - 1.8))
    header_y = y + h - row_h

    out.append("0 setgray 0.25 setlinewidth")
    ps_line(out, x, header_y - 2, x + min(total_w, w), header_y - 2)

    cur_x = x
    for idx, header in enumerate(headers):
        align = "left" if idx == 0 else "right"
        text_x = cur_x + (2 if idx == 0 else widths[idx] - 2)
        ps_text(out, text_x, header_y, header, size=font_size, font="Courier-Bold", align=align)
        cur_x += widths[idx]

    formatters = {
        "gb_up": fmt_gb,
        "gb_down": fmt_gb,
        "gb_total": fmt_gb,
        "d_u_ratio": fmt_ratio,
        "p_up": fmt_prob,
        "p_down": fmt_prob,
        "p_total": fmt_prob,
        "inv_n_up": fmt_n,
        "inv_n_down": fmt_n,
        "inv_n_total": fmt_n,
    }

    for row_idx, row in enumerate(rows):
        row_y = header_y - (row_idx + 1) * row_h
        if row_y < y:
            break
        if row_idx % 5 == 4:
            out.append("0.90 setgray 0.15 setlinewidth")
            ps_line(out, x, row_y - 2, x + min(total_w, w), row_y - 2)
            out.append("0 setgray")

        cur_x = x
        for col_idx, key in enumerate(keys):
            if key == "label":
                value = row.label
            else:
                value = formatters[key](row.values.get(key))
            align = "left" if col_idx == 0 else "right"
            text_x = cur_x + (2 if col_idx == 0 else widths[col_idx] - 2)
            ps_text(out, text_x, row_y, value, size=font_size, font="Courier", align=align)
            cur_x += widths[col_idx]


def render_postscript(json_path: Path, ps_path: Path, data: dict[str, Any], rows: list[ReportRow]) -> None:
    out: list[str] = [
        "%!PS-Adobe-3.0",
        "%%Creator: bw_rpts_report.py",
        "%%Pages: 1",
        "%%BoundingBox: 0 0 612 792",
        "%%DocumentMedia: Letter 612 792 0 () ()",
        "%%EndComments",
        "0 setlinejoin 0 setlinecap",
    ]

    margin = 18.0
    title = f"Bandwidth usage report  {json_path.name}"
    subtitle = f"data_when {data.get('data_when', '')}   response_when {data.get('response_when', '')}"
    ps_text(out, margin, LETTER_H - 14, title, size=8.0, font="Helvetica-Bold")
    ps_text(out, margin, LETTER_H - 23, subtitle, size=5.4)

    chart_w = LETTER_W - 2 * margin
    chart_h = 126.0
    gap = 8.0
    chart_top = LETTER_H - 34.0
    chart1_y = chart_top - chart_h
    chart2_y = chart1_y - gap - chart_h
    chart3_y = chart2_y - gap - chart_h

    if rows:
        draw_usage_chart(out, rows, margin, chart1_y, chart_w, chart_h)
        draw_probability_chart(out, rows, margin, chart2_y, chart_w, chart_h)
        draw_incidence_chart(out, rows, margin, chart3_y, chart_w, chart_h)
        draw_table(out, rows, margin, margin, chart_w, chart3_y - margin - 10)
    else:
        ps_text(out, margin, LETTER_H / 2, "No bandwidth rows found.", size=10.0)

    out.extend(["showpage", "%%EOF", ""])
    ps_path.parent.mkdir(parents=True, exist_ok=True)
    ps_path.write_text("\n".join(out), encoding="ascii")
    os.chmod(ps_path, 0o644)


def run_lpr(ps_path: Path, lpr_options: list[str]) -> None:
    subprocess.run(["lpr", *lpr_options, str(ps_path)], check=True)


def parse_report_date(value: str | None) -> date | None:
    if value is None:
        return None
    for fmt in ("%Y-%m-%d", "%y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"invalid report date {value!r}; use YYYY-MM-DD or YYMMDD")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse vnstat JSON/CSV, score usage, render one-page PostScript, and optionally print."
    )
    parser.add_argument("--input-dir", type=Path, default=Path("/var/spool/bandwidth-usage"))
    parser.add_argument("--output-dir", type=Path, default=None, help="default: input-dir")
    parser.add_argument("--scorer", type=Path, default=Path(__file__).with_name("score_bandwidth_usage.py"))
    parser.add_argument("--date", dest="report_date", help="report date as YYYY-MM-DD or YYMMDD; default: latest daily row")
    parser.add_argument("--previous-months", type=int, default=2)
    parser.add_argument("--include-zero-days", action="store_true")
    parser.add_argument("--include-zero-months", action="store_true")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--ps-out", type=Path)
    parser.add_argument("--print", dest="do_print", action="store_true", help="send the PostScript report to lpr")
    parser.add_argument("--lpr-option", action="append", default=[], help="extra lpr option, repeatable")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    input_dir = args.input_dir.resolve()
    output_dir = (args.output_dir or args.input_dir).resolve()

    monthly_path, monthly_rows = load_source_rows(input_dir, "monthly", daily=False)
    daily_path, daily_rows = load_source_rows(input_dir, "daily", daily=True)
    report_day = parse_report_date(args.report_date) or infer_report_date(daily_rows)
    suffix = report_day.strftime("%y%m%d")

    data = build_bandwidth_usage(
        monthly_rows=monthly_rows,
        daily_rows=daily_rows,
        report_day=report_day,
        previous_months=max(0, args.previous_months),
        include_zero_days=args.include_zero_days,
        include_zero_months=args.include_zero_months,
    )

    json_path = (args.json_out or output_dir / f"bandwidth_usage.{suffix}.json").resolve()
    ps_path = (args.ps_out or output_dir / f"bandwidth_usage.{suffix}.ps").resolve()

    write_json_atomic(json_path, data)
    score_bandwidth_usage(json_path, args.scorer.resolve())
    scored_data, rows = load_report_rows(json_path)
    render_postscript(json_path, ps_path, scored_data, rows)

    if args.do_print:
        run_lpr(ps_path, args.lpr_option)

    print(f"monthly_source={monthly_path}")
    print(f"daily_source={daily_path}")
    print(f"json_out={json_path}")
    print(f"postscript_out={ps_path}")
    print(f"rows={len(rows)}")
    if args.do_print:
        print("printed=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
