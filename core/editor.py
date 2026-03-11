"""Video editor pipeline — cut, effects, text, music, export."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from moviepy import VideoFileClip, concatenate_videoclips

from config import settings
from core.effects import apply_zoom, apply_slowmo, apply_shake, crossfade_clips
from core.text_overlay import add_text_to_clip
from core.music import overlay_music

log = logging.getLogger(__name__)

# Types that benefit from slowmo (dramatic effect)
SLOWMO_TYPES = {"kill", "clutch", "hit", "dodge"}
# Types that benefit from shake (impact feel)
SHAKE_TYPES = {"kill", "hit", "clutch"}


@dataclass
class MontageSettings:
    effects: dict = field(default_factory=lambda: {
        "zoom": True, "slowmo": True, "shake": False
    })
    text_on: bool = True
    music_path: str | None = None


def process_video(
    video_path: str,
    moments: list[dict],
    montage_settings: MontageSettings,
) -> Path:
    """Main processing pipeline. Runs in a thread (blocking)."""
    log.info("Starting montage: %d moments, effects=%s", len(moments), montage_settings.effects)

    source = VideoFileClip(video_path)
    duration = source.duration
    source_fps = source.fps or 30

    # Filter out moments beyond video duration and cap at 30
    moments = [m for m in moments if m["start_sec"] < duration]
    if len(moments) > 30:
        # Keep top 30 by intensity
        moments.sort(key=lambda x: x.get("intensity", 5), reverse=True)
        moments = moments[:30]
        moments.sort(key=lambda x: x["start_sec"])
    log.info("After filtering: %d moments (video duration: %.1fs)", len(moments), duration)

    # Extract clips for each moment
    clips = []
    for m in moments:
        start = max(0, m["start_sec"])
        end = min(duration, m["end_sec"])
        if end <= start:
            continue

        clip = source.subclipped(start, end)
        intensity = m.get("intensity", 5)
        mtype = m.get("moment_type", "other")

        # Smart effects based on moment type + intensity
        if montage_settings.effects.get("zoom"):
            # Stronger zoom on high-intensity moments
            clip = apply_zoom(clip, intensity)

        if montage_settings.effects.get("slowmo"):
            # Slowmo only on dramatic moments with high intensity
            if mtype in SLOWMO_TYPES and intensity >= 7:
                clip = apply_slowmo(clip, factor=0.4)
            elif intensity >= 9:
                # Epic moments always get slowmo
                clip = apply_slowmo(clip, factor=0.5)

        if montage_settings.effects.get("shake"):
            if mtype in SHAKE_TYPES and intensity >= 5:
                clip = apply_shake(clip, intensity)

        # Text overlay
        if montage_settings.text_on and m.get("description"):
            clip = add_text_to_clip(clip, m["description"])

        clips.append(clip)

    if not clips:
        source.close()
        raise ValueError("No valid clips extracted")

    # Crop to vertical 9:16 for TikTok
    clips = [_crop_vertical(c) for c in clips]

    # Concatenate with transitions
    final = crossfade_clips(clips, fade_duration=0.3)

    # Overlay music
    if montage_settings.music_path:
        final = overlay_music(final, montage_settings.music_path)

    # Export — TikTok optimal: 1080x1920, h264, 30fps, high bitrate
    output_path = settings.temp_dir / f"montage_{Path(video_path).stem}.mp4"
    log.info("Exporting to %s", output_path)

    # Use source fps capped at 60
    out_fps = min(source_fps, 60)

    final.write_videofile(
        str(output_path),
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="192k",
        fps=out_fps,
        preset="medium",  # better quality than "fast"
        bitrate="10000k",  # high quality for TikTok
        ffmpeg_params=[
            "-pix_fmt", "yuv420p",    # max compatibility
            "-movflags", "+faststart", # streaming-friendly
            "-profile:v", "high",      # h264 high profile
            "-level", "4.1",
        ],
        logger=None,
    )

    # Cleanup
    source.close()
    for c in clips:
        try:
            c.close()
        except Exception:
            pass

    log.info("Montage complete: %s (%.1fMB)", output_path,
             output_path.stat().st_size / 1024 / 1024)
    return output_path


def _crop_vertical(clip) -> object:
    """Crop horizontal video to 9:16 vertical (center crop). Ensures even dimensions for h264."""
    w, h = clip.size
    target_ratio = 9 / 16

    current_ratio = w / h
    if abs(current_ratio - target_ratio) < 0.05:
        # Already roughly vertical — just ensure even dimensions
        return _ensure_even(clip)

    if current_ratio > target_ratio:
        # Wider than 9:16 — crop sides
        new_w = int(h * target_ratio)
        new_w = new_w - (new_w % 2)  # ensure even
        x1 = (w - new_w) // 2
        return clip.cropped(x1=x1, x2=x1 + new_w)
    else:
        # Taller than 9:16 — crop top/bottom
        new_h = int(w / target_ratio)
        new_h = new_h - (new_h % 2)  # ensure even
        y1 = (h - new_h) // 2
        return clip.cropped(y1=y1, y2=y1 + new_h)


def _ensure_even(clip) -> object:
    """Ensure clip has even width and height (h264 requirement)."""
    w, h = clip.size
    new_w = w - (w % 2)
    new_h = h - (h % 2)
    if new_w == w and new_h == h:
        return clip
    return clip.cropped(x1=0, x2=new_w, y1=0, y2=new_h)
