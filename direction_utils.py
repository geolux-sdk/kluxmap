from __future__ import annotations

import numpy as np

DIRECTION_LABELS = ("BU", "LR", "TD", "RL")
_DIRECTION_OFFSETS = {
    "BU": 0.0,
    "LR": 90.0,
    "TD": 180.0,
    "RL": 270.0,
}


def normalize_azimuth(angle_deg: float) -> float:
    return float(angle_deg) % 360.0


def angular_difference(angle_a_deg: float, angle_b_deg: float) -> float:
    diff = (float(angle_a_deg) - float(angle_b_deg) + 180.0) % 360.0 - 180.0
    return abs(diff)


def heading_from_deltas(dx, dy):
    dx_arr = np.asarray(dx, dtype=float)
    dy_arr = np.asarray(dy, dtype=float)
    headings = (np.degrees(np.arctan2(dx_arr, dy_arr)) + 360.0) % 360.0
    stationary = (dx_arr == 0.0) & (dy_arr == 0.0)
    headings = np.where(stationary, np.nan, headings)

    if np.ndim(headings) == 0:
        value = float(headings)
        return None if np.isnan(value) else value
    return headings


def heading_from_points(start_x: float, start_y: float, end_x: float, end_y: float):
    return heading_from_deltas(end_x - start_x, end_y - start_y)


def direction_heading(direction: str, main_bearing_deg: float) -> float:
    return normalize_azimuth(main_bearing_deg + _DIRECTION_OFFSETS[direction])


def classify_heading(heading_deg: float, main_bearing_deg: float) -> str:
    diff = normalize_azimuth(heading_deg - main_bearing_deg)
    if diff <= 45.0 or diff > 315.0:
        return "BU"
    if diff <= 135.0:
        return "LR"
    if diff <= 225.0:
        return "TD"
    return "RL"


def classify_points(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    main_bearing_deg: float,
) -> str | None:
    heading = heading_from_points(start_x, start_y, end_x, end_y)
    if heading is None:
        return None
    return classify_heading(heading, main_bearing_deg)


def heading_matches_project_directions(
    heading_deg, main_bearing_deg: float, tolerance_deg: float
):
    heading_arr = np.asarray(heading_deg, dtype=float)
    targets = np.asarray(
        [direction_heading(direction, main_bearing_deg) for direction in DIRECTION_LABELS],
        dtype=float,
    )
    diffs = np.abs((targets[:, None] - heading_arr + 180.0) % 360.0 - 180.0)
    matches = np.any(diffs <= float(tolerance_deg), axis=0)

    if np.ndim(heading_arr) == 0:
        return bool(matches)
    return matches
