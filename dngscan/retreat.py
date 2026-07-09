# SPDX-License-Identifier: GPL-3.0-or-later
"""Clip-driven chroma retreat for the luminance tone core."""
from __future__ import annotations

from typing import Any

from ._deps import np
from .color import RGB_TO_XYZ, luminance_from_rec2020

REC2020_Y_ROW_SUM = float(RGB_TO_XYZ["Rec2020"][1].sum())


def resize_clip_masks(clip_masks: Any, shape: tuple[int, int]) -> Any:
    """Bilinearly resize half-resolution clip masks to a render buffer shape."""
    if clip_masks is None:
        return None
    mask = np.asarray(clip_masks, dtype=np.float32)
    if mask.shape[:2] == shape:
        return mask
    from PIL import Image

    h, w = shape
    channels = []
    for idx in range(mask.shape[2]):
        im = Image.fromarray(mask[:, :, idx].astype(np.float32, copy=False), mode="F")
        im = im.resize((w, h), Image.Resampling.BILINEAR)
        channels.append(np.asarray(im, dtype=np.float32))
    return np.clip(np.stack(channels, axis=2), 0.0, 1.0)


def clip_masks_for_shape(bundle: Any, shape: tuple[int, int]) -> Any:
    """Resize bundle clip masks once per render shape (cached on the bundle)."""
    masks = getattr(bundle, "clip_masks", None)
    if masks is None:
        return None
    cache_shape = getattr(bundle, "_clip_masks_cache_shape", None)
    cached = getattr(bundle, "_clip_masks_resized", None)
    if cache_shape == shape and cached is not None:
        return cached
    resized = resize_clip_masks(masks, shape)
    bundle._clip_masks_cache_shape = shape
    bundle._clip_masks_resized = resized
    return resized


def retreat_strength_from_masks(masks_rgb: Any) -> Any:
    """Continuous R/G/B clip classing: G-only < single R/B < multi-channel clip."""
    masks = np.clip(np.asarray(masks_rgb, dtype=np.float32), 0.0, 1.0)
    mr = masks[:, 0]
    mg = masks[:, 1]
    mb = masks[:, 2]
    strength = np.float32(1.0) - (
        (np.float32(1.0) - np.float32(0.35) * mg)
        * (np.float32(1.0) - np.float32(0.50) * mr)
        * (np.float32(1.0) - np.float32(0.50) * mb)
    )
    return np.clip(strength, 0.0, 1.0)


def apply_clip_retreat_rec2020(rgb_rec2020: Any, masks_rgb: Any, strength: float = 1.0) -> Any:
    """Move clipped chroma toward the Rec.2020 neutral axis at the same luminance."""
    if masks_rgb is None or strength <= 0.0:
        return rgb_rec2020
    rgb = np.asarray(rgb_rec2020, dtype=np.float32)
    s = retreat_strength_from_masks(masks_rgb) * np.float32(max(0.0, float(strength)))
    if not np.any(s > 0.0):
        return rgb
    y = luminance_from_rec2020(rgb).astype(np.float32, copy=False)
    neutral = (y / np.float32(max(REC2020_Y_ROW_SUM, 1e-9)))[:, None]
    return (rgb + s[:, None] * (neutral - rgb)).astype(np.float32, copy=False)
