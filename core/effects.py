"""Video effects: zoom, slowmo, speedup, shake, transitions."""

import random
import math
from moviepy import VideoClip, concatenate_videoclips
import numpy as np


def apply_zoom(clip: VideoClip, zoom_level: float = 1.5) -> VideoClip:
    """Static zoom into center of clip (no animation)."""
    def zoom_effect(get_frame, t):
        frame = get_frame(t)
        h, w = frame.shape[:2]
        new_w = int(w / zoom_level)
        new_h = int(h / zoom_level)
        x1 = (w - new_w) // 2
        y1 = (h - new_h) // 2
        cropped = frame[y1:y1 + new_h, x1:x1 + new_w]
        from PIL import Image
        img = Image.fromarray(cropped)
        img = img.resize((w, h), Image.LANCZOS)
        return np.array(img)

    return clip.transform(zoom_effect)


def apply_slowmo(clip: VideoClip, factor: float = 0.5) -> VideoClip:
    """Slow down clip (0.5 = half speed)."""
    return clip.with_speed_scaled(factor)


def apply_speedup(clip: VideoClip, factor: float = 1.3) -> VideoClip:
    """Speed up clip (1.3 = 30% faster)."""
    return clip.with_speed_scaled(factor)


def apply_shake(clip: VideoClip, intensity: int = 5) -> VideoClip:
    """Camera shake effect."""
    max_disp = 2 + (intensity / 10) * 13
    duration = clip.duration
    fps = clip.fps or 30
    n_frames = int(duration * fps) + 1
    random.seed(42)
    offsets_x = [random.uniform(-max_disp, max_disp) for _ in range(n_frames)]
    offsets_y = [random.uniform(-max_disp, max_disp) for _ in range(n_frames)]

    def shake_effect(get_frame, t):
        frame = get_frame(t)
        h, w = frame.shape[:2]
        idx = min(int(t * fps), n_frames - 1)
        dx, dy = int(offsets_x[idx]), int(offsets_y[idx])
        result = np.zeros_like(frame)
        src_x1, src_y1 = max(0, dx), max(0, dy)
        src_x2, src_y2 = min(w, w + dx), min(h, h + dy)
        dst_x1, dst_y1 = max(0, -dx), max(0, -dy)
        dst_x2 = dst_x1 + (src_x2 - src_x1)
        dst_y2 = dst_y1 + (src_y2 - src_y1)
        result[dst_y1:dst_y2, dst_x1:dst_x2] = frame[src_y1:src_y2, src_x1:src_x2]
        return result

    return clip.transform(shake_effect)


def crossfade_clips(clips: list[VideoClip], fade_duration: float = 0.3) -> VideoClip:
    """Concatenate clips with crossfade."""
    if len(clips) <= 1:
        return clips[0] if clips else None
    safe_fade = min(fade_duration, min(c.duration for c in clips) / 2)
    if safe_fade < 0.05:
        return concatenate_videoclips(clips)
    return concatenate_videoclips(clips, transition=None, padding=-safe_fade)
