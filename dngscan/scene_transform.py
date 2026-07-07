# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene-linear pre-AgX colour transforms.

This layer sits after camera colour interpretation and before AgX.  It is not a
display look: the operator keeps scene-linear values scene-linear, leaves the
neutral axis unchanged, and only blends a constrained 3x3 matrix inside soft
chromaticity windows.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._deps import np

EPS = 1e-8
SCENE_TRANSFORM_PRESETS_JSON = Path(__file__).with_name("scene_transform_presets.json")


@dataclass(frozen=True)
class SceneTransformRegion:
    name: str
    matrix: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
    mu_rg_bg: tuple[float, float]
    cov_rg_bg: tuple[tuple[float, float], tuple[float, float]]
    scale: float = 2.5
    strength: float = 1.0


@dataclass(frozen=True)
class SceneTransformPreset:
    name: str
    label: str
    illuminant: str
    working_space: str
    regions: tuple[SceneTransformRegion, ...]
    note: str = ""


def _region_from_dict(name: str, raw: dict[str, Any]) -> SceneTransformRegion:
    return SceneTransformRegion(
        name=str(raw.get("name", name)),
        matrix=tuple(tuple(float(v) for v in row) for row in raw["matrix"]),  # type: ignore[arg-type]
        mu_rg_bg=tuple(float(v) for v in raw["mu_rg_bg"]),  # type: ignore[arg-type]
        cov_rg_bg=tuple(tuple(float(v) for v in row) for row in raw["cov_rg_bg"]),  # type: ignore[arg-type]
        scale=float(raw.get("scale", 2.5)),
        strength=float(raw.get("strength", 1.0)),
    )


def _preset_from_dict(name: str, raw: dict[str, Any]) -> SceneTransformPreset:
    regions_raw = raw.get("regions", [])
    regions = tuple(_region_from_dict(str(i), r) for i, r in enumerate(regions_raw) if isinstance(r, dict))
    return SceneTransformPreset(
        name=str(raw.get("name", name)),
        label=str(raw.get("label", name)),
        illuminant=str(raw.get("illuminant", "")),
        working_space=str(raw.get("working_space", "Rec2020")),
        regions=regions,
        note=str(raw.get("note", "")),
    )


def _load_presets() -> dict[str, SceneTransformPreset]:
    presets: dict[str, SceneTransformPreset] = {}
    try:
        raw = json.loads(SCENE_TRANSFORM_PRESETS_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    transforms = raw.get("transforms", raw) if isinstance(raw, dict) else {}
    if isinstance(transforms, dict):
        for name, item in transforms.items():
            if not isinstance(name, str) or not isinstance(item, dict):
                continue
            try:
                preset = _preset_from_dict(name, item)
            except (KeyError, TypeError, ValueError):
                continue
            if preset.regions:
                presets[name] = preset
    return presets


SCENE_TRANSFORMS: dict[str, SceneTransformPreset] = _load_presets()
SCENE_TRANSFORM_CHOICES = ("none",) + tuple(SCENE_TRANSFORMS)


def scene_transform_label(name: str) -> str:
    if name == "none":
        return "无"
    preset = SCENE_TRANSFORMS.get(name)
    return preset.label if preset is not None else name.replace("_", " ")


def validate_scene_transform(name: str) -> str:
    if name == "none" or name in SCENE_TRANSFORMS:
        return name
    raise ValueError(f"未知 scene transform：{name}")


def _apply_matrix(rgb: Any, matrix: Any) -> Any:
    out = np.empty_like(rgb, dtype=np.float32)
    out[:, 0] = matrix[0, 0] * rgb[:, 0] + matrix[0, 1] * rgb[:, 1] + matrix[0, 2] * rgb[:, 2]
    out[:, 1] = matrix[1, 0] * rgb[:, 0] + matrix[1, 1] * rgb[:, 1] + matrix[1, 2] * rgb[:, 2]
    out[:, 2] = matrix[2, 0] * rgb[:, 0] + matrix[2, 1] * rgb[:, 1] + matrix[2, 2] * rgb[:, 2]
    return out


def _region_weight(rgb: Any, region: SceneTransformRegion) -> Any:
    denom = np.maximum(rgb[:, 1], np.float32(EPS))
    chroma = np.empty((rgb.shape[0], 2), dtype=np.float32)
    chroma[:, 0] = rgb[:, 0] / denom
    chroma[:, 1] = rgb[:, 2] / denom

    mu = np.asarray(region.mu_rg_bg, dtype=np.float32)
    cov = np.asarray(region.cov_rg_bg, dtype=np.float32) * np.float32(max(region.scale, EPS) ** 2)
    try:
        inv_cov = np.linalg.inv(cov).astype(np.float32, copy=False)
    except np.linalg.LinAlgError:
        inv_cov = np.linalg.pinv(cov).astype(np.float32, copy=False)
    d = chroma - mu[None, :]
    mahal = d[:, 0] * (inv_cov[0, 0] * d[:, 0] + inv_cov[0, 1] * d[:, 1])
    mahal += d[:, 1] * (inv_cov[1, 0] * d[:, 0] + inv_cov[1, 1] * d[:, 1])
    weight = np.exp(np.clip(-0.5 * mahal, -80.0, 0.0)).astype(np.float32, copy=False)
    signal = np.max(rgb, axis=1)
    return np.where(signal > np.float32(EPS), weight, np.float32(0.0))


def apply_scene_transform_rec2020(rgb: Any, transform: str = "none", strength: float = 1.0) -> Any:
    """Apply a soft chromaticity-windowed 3x3 scene transform in linear Rec.2020.

    `strength=0` is exact identity.  Multiple regions blend by normalizing only
    when their raw weights sum above one, so a single region keeps its full mask
    while overlap cannot double-apply competing matrices.
    """
    if transform == "none" or strength <= 0.0:
        return rgb
    preset = SCENE_TRANSFORMS.get(transform)
    if preset is None or not preset.regions:
        return rgb

    rgb32 = np.nan_to_num(rgb.astype(np.float32, copy=False), nan=0.0, posinf=1e6, neginf=0.0)
    weights: list[Any] = []
    for region in preset.regions:
        weights.append(_region_weight(rgb32, region) * np.float32(max(0.0, region.strength)))
    total = np.zeros((rgb32.shape[0],), dtype=np.float32)
    for w in weights:
        total += w
    norm = np.maximum(total, np.float32(1.0))

    out = rgb32.copy()
    global_strength = np.float32(max(0.0, float(strength)))
    for region, weight in zip(preset.regions, weights):
        w = (weight / norm * global_strength).astype(np.float32, copy=False)
        if not bool(np.any(w > 1e-6)):
            continue
        matrix = np.asarray(region.matrix, dtype=np.float32)
        mapped = _apply_matrix(rgb32, matrix)
        out += w[:, None] * (mapped - rgb32)
    return np.nan_to_num(out, nan=0.0, posinf=1e6, neginf=-1e6)
