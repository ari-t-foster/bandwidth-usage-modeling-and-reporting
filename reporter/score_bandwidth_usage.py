#!/usr/bin/env python3
"""Score monthly bandwidth usage JSON with the selected historical model."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scipy import stats


MODEL_SLUG = "OVBI_2026_2027_Model6 1.0"

# Selected model:
# overall: #1 H=gamma, S=gamma, t=100, u=5000, alpha=2.5, n=1M
# download: same body, alpha_direction=5.0
# upload: same body, alpha_direction=4.0
# Period rule: 2026 -> 1Q26; 2027+ -> 1Q27. Earlier years fall back to 1Q26.
MODELS = {
    "1Q26": {
        "total": {
            "alpha": 2.5,
            "scale": 1.0,
            "s_t": 0.789903387753975,
            "s_u": 0.006848390450080104,
            "head_shape": 0.10000000000002844,
            "head_scale": 1.00000000000042,
            "shoulder_shape": 1.3921245448962443,
            "shoulder_scale": 573.7879756052461,
        },
        "down": {
            "alpha": 5.0,
            "scale": 0.9393554594896322,
            "s_t": 0.789903387753975,
            "s_u": 0.006848390450080104,
            "head_shape": 0.10000000000002844,
            "head_scale": 1.00000000000042,
            "shoulder_shape": 1.3921245448962443,
            "shoulder_scale": 573.7879756052461,
        },
        "up": {
            "alpha": 4.0,
            "scale": 0.08022046253997142,
            "s_t": 0.789903387753975,
            "s_u": 0.006848390450080104,
            "head_shape": 0.10000000000002844,
            "head_scale": 1.00000000000042,
            "shoulder_shape": 1.3921245448962443,
            "shoulder_scale": 573.7879756052461,
        },
    },
    "1Q27": {
        "total": {
            "alpha": 2.5,
            "scale": 1.0,
            "s_t": 0.8004306090075439,
            "s_u": 0.009683583326517278,
            "head_shape": 0.10000000000013654,
            "head_scale": 1.0000000000015845,
            "shoulder_shape": 1.5233350223742028,
            "shoulder_scale": 575.4451287385396,
        },
        "down": {
            "alpha": 5.0,
            "scale": 0.9430927495806822,
            "s_t": 0.8004306090075439,
            "s_u": 0.009683583326517278,
            "head_shape": 0.10000000000013654,
            "head_scale": 1.0000000000015845,
            "shoulder_shape": 1.5233350223742028,
            "shoulder_scale": 575.4451287385396,
        },
        "up": {
            "alpha": 4.0,
            "scale": 0.08498338804245818,
            "s_t": 0.8004306090075439,
            "s_u": 0.009683583326517278,
            "head_shape": 0.10000000000013654,
            "head_scale": 1.0000000000015845,
            "shoulder_shape": 1.5233350223742028,
            "shoulder_scale": 575.4451287385396,
        },
    },
}


def gamma_cdf(x: float, shape: float, scale: float) -> float:
    if x <= 0:
        return 0.0
    if math.isinf(x):
        return 1.0
    return float(stats.gamma.cdf(x, a=shape, scale=scale))


def exceedance_probability(gb: float | None, params: dict[str, float]) -> float | None:
    if gb is None or not math.isfinite(gb) or gb < 0:
        return None

    t_gb = 100.0
    u_gb = 5000.0
    x = gb / params["scale"]

    if x <= 0:
        return 1.0

    s_t = params["s_t"]
    s_u = params["s_u"]
    alpha = params["alpha"]

    head_mass = 1.0 - s_t
    shoulder_mass = s_t - s_u

    head_t = gamma_cdf(t_gb, params["head_shape"], params["head_scale"])
    shoulder_t = gamma_cdf(t_gb, params["shoulder_shape"], params["shoulder_scale"])
    shoulder_u = gamma_cdf(u_gb, params["shoulder_shape"], params["shoulder_scale"])
    shoulder_denom = shoulder_u - shoulder_t

    if x < t_gb:
        cdf = head_mass * gamma_cdf(x, params["head_shape"], params["head_scale"]) / head_t
        return max(0.0, min(1.0, 1.0 - cdf))

    if x < u_gb:
        shoulder_progress = (
            gamma_cdf(x, params["shoulder_shape"], params["shoulder_scale"]) - shoulder_t
        ) / shoulder_denom
        cdf = head_mass + shoulder_mass * shoulder_progress
        return max(0.0, min(1.0, 1.0 - cdf))

    return max(0.0, min(1.0, s_u * (x / u_gb) ** (-alpha)))


def inv_n(p: float | None) -> float | None:
    if p is None or p <= 0:
        return None
    return 1.0 / p


def parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def infer_year(label: str, point: dict[str, Any]) -> int | None:
    if point.get("year") not in (None, ""):
        try:
            return int(point["year"])
        except (TypeError, ValueError):
            pass

    match = re.search(r"(20\d{2})", str(label))
    if match:
        return int(match.group(1))
    return None


def period_for(label: str, point: dict[str, Any]) -> str:
    year = infer_year(label, point)
    return "1Q27" if year is not None and year >= 2027 else "1Q26"


def score_point(label: str, point: dict[str, Any]) -> dict[str, Any]:
    period = period_for(label, point)
    model = MODELS[period]

    p_up = exceedance_probability(parse_float(point.get("gb_up")), model["up"])
    p_down = exceedance_probability(parse_float(point.get("gb_down")), model["down"])
    p_total = exceedance_probability(parse_float(point.get("gb_total")), model["total"])

    return {
        "period": period,
        "p_up": p_up,
        "inv_n_up": inv_n(p_up),
        "p_down": p_down,
        "inv_n_down": inv_n(p_down),
        "p_total": p_total,
        "inv_n_total": inv_n(p_total),
    }


def iter_points(data_points: Any):
    if isinstance(data_points, dict):
        for label, point in data_points.items():
            if isinstance(point, dict):
                yield label, point
        return

    if isinstance(data_points, list):
        for item in data_points:
            if isinstance(item, dict) and len(item) == 1:
                label, point = next(iter(item.items()))
                if isinstance(point, dict):
                    yield label, point


def score_data_points(data_points: Any) -> Any:
    if isinstance(data_points, dict):
        return {label: score_point(label, point) for label, point in iter_points(data_points)}

    if isinstance(data_points, list):
        scored = []
        for label, point in iter_points(data_points):
            scored.append({label: score_point(label, point)})
        return scored

    return {}


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path = path.resolve()
    mode = path.stat().st_mode
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(data, tmp, indent=2, sort_keys=False)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.chmod(tmp_path, mode)
    os.replace(tmp_path, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Graft usage exceedance response onto JSON.")
    parser.add_argument("json_path", type=Path)
    args = parser.parse_args()

    with args.json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    data["response"] = {
        "model_slug": MODEL_SLUG,
        "data_points": score_data_points(data.get("data_points", {})),
    }
    data["response_when"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    write_json_atomic(args.json_path, data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
