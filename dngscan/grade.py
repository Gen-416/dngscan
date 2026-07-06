# SPDX-License-Identifier: GPL-3.0-or-later
"""Unified grade picker: chromatic look OR display filter, never both."""
from __future__ import annotations

from .display_filter import DISPLAY_FILTERS, FILTER_CHOICES
from .look import LOOK_CHOICES, LOOK_FIELDS

RENDER_MODE = "agx"

_LOOK_LABELS = {
    "none": "无",
    "classic": "ARRI Classic 709",
    "reveal": "ARRI Reveal 709",
}


def grade_label(name: str) -> str:
    if name == "none":
        return "无"
    if name in DISPLAY_FILTERS:
        return DISPLAY_FILTERS[name].label
    return _LOOK_LABELS.get(name, name.replace("fuji_", "Fujifilm ").replace("_", " "))


def grade_choices() -> tuple[str, ...]:
    looks = tuple(n for n in LOOK_CHOICES if n != "none")
    filters = tuple(n for n in FILTER_CHOICES if n != "none")
    return ("none",) + looks + filters


def is_filter_grade(name: str) -> bool:
    return name in DISPLAY_FILTERS


def is_look_grade(name: str) -> bool:
    return name in LOOK_FIELDS


def resolve_grade(name: str, strength: float) -> tuple[str, float, str, float]:
    """Map a single grade id to (look, look_strength, filter, filter_strength)."""
    s = max(0.0, min(1.5, float(strength)))
    if name == "none":
        return "none", 0.0, "none", 0.0
    if name in DISPLAY_FILTERS:
        return "none", 0.0, name, s
    if name in LOOK_FIELDS:
        return name, s, "none", 0.0
    raise ValueError(f"未知成片风格：{name}")


def resolve_grade_params(params: dict) -> tuple[str, float, str, float]:
    """Accept unified `grade` or legacy separate look/filter (mutually exclusive)."""
    grade = params.get("grade")
    if grade is not None:
        strength = float(params.get("gradeStrength", params.get("grade_strength", 1.0)))
        return resolve_grade(str(grade), strength)

    look = str(params.get("look", "none"))
    filt = str(params.get("filter", "none"))
    if look != "none" and filt != "none":
        raise ValueError("色度 Look 与输出滤镜不能同时选用，请只选一种成片风格")
    look_strength = float(params.get("lookStrength", 1.0))
    filter_strength = float(params.get("filterStrength", 1.0))
    if filt != "none":
        return resolve_grade(filt, filter_strength)
    if look != "none":
        return resolve_grade(look, look_strength)
    return "none", 0.0, "none", 0.0
