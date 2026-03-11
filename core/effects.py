"""Video effects: zoom, slowmo, shake, transitions."""

import random
import math
from moviepy import (
    VideoClip,
    VideoFileClip,
    concatenate_videoclips,
    CompositeVideoClip,
)
import numpy as np


def apply_zoom(clip: VideoClip, intensity: int = 5) -> VideoClip:
    """Smooth zoom into center of clip. intensity 1-10 maps to 1.1x-1.8x."""
    max_zoom = 1.1 + (intensity / 10) * 0.7  # 1.1x to 1.8x
    duration = clip.duration

    def zoom_effect(get_frame, t):
        progress = t / duration if duration > 0 else 0
        # Ease-in-out curve
        scale = 1 + (max_zoom - 1) * (0.5 - 0.5 * math.cos(math.pi * progress))

        frame = get_frame(t)
        h, w = frame.shape[:2]

        # Calculate crop dimensions
        new_w = int(w / scale)
        new_h = int(h / scale)
        x1 = (w - new_w) // 2
        y1 = (h - new_h) // 2

        cropped = frame[y1:y1 + new_h, x1:x1 + new_w]

        # Resize back to original dimensions
        from PIL import Image
        img = Image.fromarray(cropped)
        img = img.resize((w, h), Image.LANCZOS)
        return np.array(img)

    return clip.transform(zoom_effect)


def apply_slowmo(clip: VideoClip, factor: float = 0.5) -> VideoClip:
    """Slow down clip by factor (0.5 = half speed)."""
    return clip.with_speed_scaled(factor)


def apply_shake(clip: VideoClip, intensity: int = 5) -> VideoClip:
    """Camera shake effect. intensity 1-10 maps to 2-15px displacement."""
    max_displacement = 2 + (intensity / 10) * 13  # 2px to 15px
    duration = clip.duration

    # Pre-generate shake offsets for consistency
    fps = clip.fps or 30
    n_frames = int(duration * fps) + 1
    random.seed(42)  # reproducible
    offsets_x = [random.uniform(-max_displacement, max_displacement) for _ in range(n_frames)]
    offsets_y = [random.uniform(-max_displacement, max_displacement) for _ in range(n_frames)]

    def shake_effect(get_frame, t):
        frame = get_frame(t)
        h, w = frame.shape[:2]
        idx = min(int(t * fps), n_frames - 1)
        dx = int(offsets_x[idx])
        dy = int(offsets_y[idx])

        # Create shifted frame with black border fill
        result = np.zeros_like(frame)
        src_x1 = max(0, dx)
        src_y1 = max(0, dy)
        src_x2 = min(w, w + dx)
        src_y2 = min(h, h + dy)
        dst_x1 = max(0, -dx)
        dst_y1 = max(0, -dy)
        dst_x2 = dst_x1 + (src_x2 - src_x1)
        dst_y2 = dst_y1 + (src_y2 - src_y1)

        result[dst_y1:dst_y2, dst_x1:dst_x2] = frame[src_y1:src_y2, src_x1:src_x2]
        return result

    return clip.transform(shake_effect)


def crossfade_clips(clips: list[VideoClip], fade_duration: float = 0.3) -> VideoClip:
    """Concatenate clips with crossfade transitions."""
    if len(clips) <= 1:
        return clips[0] if clips else None

    # Ensure fade doesn't exceed clip duration
    safe_fade = min(fade_duration, min(c.duration for c in clips) / 2)
    if safe_fade < 0.05:
        return concatenate_videoclips(clips)

    return concatenate_videoclips(clips, transition=None, padding=-safe_fade)
