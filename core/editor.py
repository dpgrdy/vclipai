"""Video editor — segment-based editing with point effects."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from moviepy import VideoFileClip, concatenate_videoclips

from config import settings
from core.effects import apply_zoom, apply_slowmo, apply_shake, apply_speedup
from core.music import overlay_music

log = logging.getLogger(__name__)


@dataclass
class MontageSettings:
    effects: dict = field(default_factory=lambda: {
        "zoom": True, "slowmo": True, "shake": True
    })
    text_on: bool = True
    music_path: str | None = None
    crop_vertical: bool = True


def process_video(
    video_path: str,
    edit_data: dict,
    montage_settings: MontageSettings,
) -> Path:
    """Segment-based editor: extract continuous segments, apply point effects."""
    segments = edit_data.get("segments", [])
    effects = edit_data.get("effects", [])

    log.info("Starting montage: %d segments, %d effects", len(segments), len(effects))

    source = VideoFileClip(video_path)
    duration = source.duration
    source_fps = source.fps or 30

    # Filter segments beyond video duration
    segments = [s for s in segments if s["start"] < duration]
    for s in segments:
        s["end"] = min(s["end"], duration)

    log.info("After filtering: %d segments (video: %.1fs)", len(segments), duration)

    if not segments:
        source.close()
        raise ValueError("No valid segments")

    # Build effect lookup: which effects fall within which segment
    def effects_in_range(start, end):
        return [e for e in effects if start <= e["at"] < end]

    clips = []
    for seg in segments:
        seg_start = max(0, seg["start"])
        seg_end = seg["end"]
        if seg_end <= seg_start or (seg_end - seg_start) < 0.3:
            continue

        seg_effects = effects_in_range(seg_start, seg_end)

        if not seg_effects or not montage_settings.effects.get("zoom"):
            # No effects in this segment — extract as one continuous clip
            clip = source.subclipped(seg_start, seg_end)
            clips.append(clip)
        else:
            # Split segment around effect points
            sub_clips = _apply_point_effects(
                source, seg_start, seg_end, seg_effects, montage_settings
            )
            clips.extend(sub_clips)

    if not clips:
        source.close()
        raise ValueError("No valid clips extracted")

    # Crop to 9:16 if needed
    if montage_settings.crop_vertical:
        clips = [_crop_vertical(c) for c in clips]
    else:
        clips = [_ensure_even(c) for c in clips]

    # Concatenate — hard cuts
    final = concatenate_videoclips(clips, method="compose")

    if montage_settings.music_path:
        final = overlay_music(final, montage_settings.music_path)

    output_path = settings.temp_dir / f"montage_{Path(video_path).stem}.mp4"
    log.info("Exporting to %s (%.1fs)", output_path, final.duration)

    out_fps = min(source_fps, 30)

    final.write_videofile(
        str(output_path),
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="128k",
        fps=out_fps,
        preset="fast",
        ffmpeg_params=[
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-profile:v", "high",
            "-level", "4.1",
        ],
        logger=None,
    )

    source.close()
    for c in clips:
        try:
            c.close()
        except Exception:
            pass

    size_mb = output_path.stat().st_size / 1024 / 1024
    log.info("Montage complete: %s (%.1fMB, %.1fs)", output_path, size_mb, final.duration)
    return output_path


def _apply_point_effects(source, seg_start, seg_end, effects, settings):
    """Split a segment around effect points and apply effects."""
    clips = []
    cursor = seg_start

    for fx in sorted(effects, key=lambda e: e["at"]):
        fx_start = max(seg_start, fx["at"] - 0.3)  # 0.3s before
        fx_end = min(seg_end, fx["at"] + fx["duration"])
        fx_type = fx["type"]

        # Before the effect — normal clip
        if cursor < fx_start:
            clips.append(source.subclipped(cursor, fx_start))

        # The effect clip
        if fx_start < fx_end:
            fx_clip = source.subclipped(fx_start, fx_end)

            if fx_type == "zoom_slowmo" and settings.effects.get("slowmo"):
                fx_clip = apply_zoom(fx_clip, zoom_level=1.6)
                fx_clip = apply_slowmo(fx_clip, factor=0.5)
            elif fx_type == "shake" and settings.effects.get("shake"):
                fx_clip = apply_shake(fx_clip, intensity=8)
                fx_clip = apply_slowmo(fx_clip, factor=0.7)
            elif fx_type == "speedup":
                fx_clip = apply_speedup(fx_clip, factor=1.5)

            clips.append(fx_clip)

        cursor = fx_end

    # After last effect — rest of segment
    if cursor < seg_end:
        clips.append(source.subclipped(cursor, seg_end))

    return clips


def _crop_vertical(clip):
    """Crop to 9:16. Even dimensions."""
    w, h = clip.size
    target_ratio = 9 / 16
    current_ratio = w / h
    if abs(current_ratio - target_ratio) < 0.05:
        return _ensure_even(clip)
    if current_ratio > target_ratio:
        new_w = int(h * target_ratio)
        new_w = new_w - (new_w % 2)
        x1 = (w - new_w) // 2
        return clip.cropped(x1=x1, x2=x1 + new_w)
    else:
        new_h = int(w / target_ratio)
        new_h = new_h - (new_h % 2)
        y1 = (h - new_h) // 2
        return clip.cropped(y1=y1, y2=y1 + new_h)


def _ensure_even(clip):
    w, h = clip.size
    new_w = w - (w % 2)
    new_h = h - (h % 2)
    if new_w == w and new_h == h:
        return clip
    return clip.cropped(x1=0, x2=new_w, y1=0, y2=new_h)
