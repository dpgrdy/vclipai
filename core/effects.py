"""Video effects: slowmo, speedup, shake."""

import random
from moviepy import VideoClip
import numpy as np


def apply_slowmo(clip: VideoClip, factor: float = 0.5) -> VideoClip:
    """Slow down clip (0.5 = half speed)."""
    return clip.with_speed_scaled(factor)


def apply_speedup(clip: VideoClip, factor: float = 1.3) -> VideoClip:
    """Speed up clip."""
    return clip.with_speed_scaled(factor)


def apply_shake(clip: VideoClip, intensity: int = 5) -> VideoClip:
    """Camera shake — clamps at edges instead of black bars."""
    max_disp = 2 + (intensity / 10) * 8
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
        # Clamp-based shift (no black bars)
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        import cv2
        return cv2.warpAffine(frame, M, (w, h), borderMode=cv2.BORDER_REPLICATE)

    return clip.transform(shake_effect)
