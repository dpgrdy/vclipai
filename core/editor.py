"""Video editor — segment-based editing with point effects."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from moviepy import VideoFileClip, concatenate_videoclips

from config import settings
from core.effects import apply_slowmo, apply_shake, apply_speedup
from core.music import overlay_music

log = logging.getLogger(__name__)


@dataclass
class MontageSettings:
    effects: dict = field(default_factory=lambda: {
        "zoom": True, "slowmo": True, "shake": True
    })
    text_on: bool = True
    music_path: str | None = None


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

    log.info("After filtering: %d segments (video: %.1fs, %dx%d, %.0ffps)",
             len(segments), duration, source.w, source.h, source_fps)

    if not segments:
        source.close()
        raise ValueError("No valid segments")

    def effects_in_range(start, end):
        return [e for e in effects if start <= e["at"] < end]

    clips = []
    for seg in segments:
        seg_start = max(0, seg["start"])
        seg_end = seg["end"]
        if seg_end <= seg_start or (seg_end - seg_start) < 0.3:
            continue

        seg_effects = effects_in_range(seg_start, seg_end)

        if not seg_effects:
            clip = source.subclipped(seg_start, seg_end)
            clips.append(clip)
        else:
            sub_clips = _apply_point_effects(
                source, seg_start, seg_end, seg_effects, montage_settings
            )
            clips.extend(sub_clips)

    if not clips:
        source.close()
        raise ValueError("No valid clips extracted")

    # Ensure even dimensions (h264 requirement)
    clips = [_ensure_even(c) for c in clips]

    # Concatenate
    final = concatenate_videoclips(clips, method="compose")

    if montage_settings.music_path:
        final = overlay_music(final, montage_settings.music_path)

    output_path = settings.temp_dir / f"montage_{Path(video_path).stem}.mp4"
    log.info("Exporting to %s (%.1fs, %dx%d)", output_path, final.duration, final.w, final.h)

    final.write_videofile(
        str(output_path),
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="192k",
        fps=source_fps,
        preset="fast",
        ffmpeg_params=[
            "-crf", "18",
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
        fx_start = max(seg_start, fx["at"] - 0.3)
        fx_end = min(seg_end, fx["at"] + fx["duration"])
        fx_type = fx["type"]

        # Before the effect — normal clip
        if cursor < fx_start - 0.05:
            clips.append(source.subclipped(cursor, fx_start))

        # The effect clip
        if fx_start < fx_end:
            fx_clip = source.subclipped(fx_start, fx_end)

            if fx_type == "zoom_slowmo" and settings.effects.get("slowmo"):
                # Just slowmo, no destructive zoom
                fx_clip = apply_slowmo(fx_clip, factor=0.4)
            elif fx_type == "shake" and settings.effects.get("shake"):
                fx_clip = apply_shake(fx_clip, intensity=6)
                fx_clip = apply_slowmo(fx_clip, factor=0.7)
            elif fx_type == "speedup":
                fx_clip = apply_speedup(fx_clip, factor=1.5)

            clips.append(fx_clip)

        cursor = fx_end

    # After last effect
    if cursor < seg_end - 0.05:
        clips.append(source.subclipped(cursor, seg_end))

    return clips


def _ensure_even(clip):
    w, h = clip.size
    new_w = w - (w % 2)
    new_h = h - (h % 2)
    if new_w == w and new_h == h:
        return clip
    return clip.cropped(x1=0, x2=new_w, y1=0, y2=new_h)
