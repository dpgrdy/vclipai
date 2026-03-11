"""Gemini video analyzer — finds moments matching user instruction."""

import json
import logging
import asyncio
import subprocess
import time as _time
from pathlib import Path
from collections import Counter

import google.generativeai as genai

from config import settings

try:
    from imageio_ffmpeg import get_ffmpeg_exe
    FFMPEG = get_ffmpeg_exe()
except ImportError:
    FFMPEG = "ffmpeg"

log = logging.getLogger(__name__)

genai.configure(api_key=settings.gemini_api_key)

SYSTEM_PROMPT = """You are a professional video editor. You create TikTok montages from gameplay recordings.

Think like a REAL video editor: you watch the full video, then decide which CONTINUOUS SEGMENTS to keep
and which to cut. You DON'T chop the video into tiny 1-second pieces — you keep natural action sequences.

TIMESTAMP FORMAT:
- TOTAL SECONDS from start. 2min 30sec = 150.0 (NOT 2.30)

Return TWO arrays in a JSON object:

1. "segments" — continuous time ranges to KEEP (everything else gets cut):
   Each segment is 3-30+ seconds of continuous action. Merge nearby actions into one segment.
   Types: "intro", "action", "climax", "outro"

2. "effects" — specific POINTS within kept segments where to apply effects:
   Types: "zoom_slowmo" (for misses/projectile tracking), "shake" (for kills/impacts), "speedup" (for repetitive hits)

Example:
{
  "segments": [
    {"start": 0, "end": 8, "type": "intro", "note": "Match start"},
    {"start": 22, "end": 65, "type": "action", "note": "First fight sequence"},
    {"start": 90, "end": 130, "type": "action", "note": "Second fight"},
    {"start": 260, "end": 275, "type": "outro", "note": "Defeat screen"}
  ],
  "effects": [
    {"at": 35.0, "duration": 2.0, "type": "zoom_slowmo", "note": "Missed shot tracking"},
    {"at": 45.0, "duration": 1.5, "type": "shake", "note": "Kill"},
    {"at": 55.0, "duration": 3.0, "type": "speedup", "note": "Rapid fire sequence"}
  ]
}

RULES:
- Segments should be CONTINUOUS chunks, not micro-clips
- Cut ONLY boring parts: walking to lane, waiting to respawn, idle time
- Keep ALL combat as one continuous segment (don't split mid-fight)
- The result should feel like a SMOOTH edit, not a choppy slideshow
- 10-20 segments max for a 5-minute video
- Follow the user's creative direction"""


def _get_duration(path: str) -> float:
    """Get video duration in seconds via moviepy."""
    try:
        from moviepy import VideoFileClip
        clip = VideoFileClip(path)
        dur = clip.duration
        clip.close()
        return dur
    except Exception:
        return 0.0


async def analyze_video(video_path: str, instruction: str) -> list[dict]:
    """Upload video to Gemini and get moment timestamps."""
    size_mb = Path(video_path).stat().st_size / (1024 * 1024)
    video_duration = await asyncio.to_thread(_get_duration, video_path)
    log.info("Uploading video to Gemini: %s (%.1fMB, %.0fs)", video_path, size_mb, video_duration)

    # Compress large videos — 10fps 720p for good game detail
    upload_path = video_path
    compressed = None
    if size_mb > 50:
        compressed = str(Path(video_path).with_suffix(".analysis.mp4"))
        t_comp = _time.monotonic()
        log.info("Compressing for analysis: %s → 10fps 720p", video_path)
        ok = await asyncio.to_thread(_compress_for_analysis, video_path, compressed)
        if ok:
            comp_mb = Path(compressed).stat().st_size / (1024 * 1024)
            log.info("Compressed in %ds: %.1fMB → %.1fMB",
                     int(_time.monotonic() - t_comp), size_mb, comp_mb)
            upload_path = compressed
        else:
            log.warning("Compression failed, uploading original")
            compressed = None

    # Upload
    t0 = _time.monotonic()
    video_file = await asyncio.to_thread(
        genai.upload_file, upload_path, mime_type="video/mp4"
    )
    upload_sec = int(_time.monotonic() - t0)
    log.info("Upload complete in %ds, waiting for processing...", upload_sec)

    await _wait_for_file(video_file)

    log.info("File ready, analyzing...")

    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT,
    )

    dur_info = ""
    if video_duration > 0:
        dur_info = (
            f"\n\nVIDEO: {video_duration:.0f} seconds ({video_duration/60:.1f} min). "
            f"All timestamps 0-{video_duration:.0f}."
        )

    prompt = (
        f"EDITING REQUEST:\n{instruction}"
        f"{dur_info}\n\n"
        "Watch the full video. Return a JSON object with 'segments' (continuous ranges to keep) "
        "and 'effects' (specific points for zoom/shake/speedup). "
        "Keep combat as continuous chunks — don't micro-chop. "
        "Return ONLY the JSON object, no markdown."
    )

    response = await asyncio.to_thread(
        model.generate_content,
        [video_file, prompt],
        generation_config=genai.GenerationConfig(
            temperature=0.1,
            max_output_tokens=65536,
        ),
    )
    resp_text = response.text or ""
    finish = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
    log.info("Gemini response: %d chars, finish_reason=%s", len(resp_text), finish)
    if len(resp_text) < 3000:
        log.info("Full response: %s", resp_text)

    # Clean up
    try:
        await asyncio.to_thread(genai.delete_file, video_file.name)
    except Exception:
        pass
    if compressed:
        try:
            Path(compressed).unlink(missing_ok=True)
        except Exception:
            pass

    return _parse_response(resp_text, video_duration)


def _compress_for_analysis(input_path: str, output_path: str) -> bool:
    """Compress video for analysis — 10fps 720p for good game detail."""
    try:
        cmd = [
            FFMPEG, "-y", "-i", input_path,
            "-vf", "fps=10,scale=-2:720",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-an",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            log.error("ffmpeg failed: %s", result.stderr[-500:].decode(errors="replace"))
            return False
        return Path(output_path).exists() and Path(output_path).stat().st_size > 0
    except Exception as e:
        log.error("Compression error: %s", e)
        return False


async def _wait_for_file(video_file, timeout: int = 600):
    elapsed = 0
    while video_file.state.name == "PROCESSING":
        if elapsed >= timeout:
            raise TimeoutError("Gemini file processing timed out")
        await asyncio.sleep(3)
        elapsed += 3
        video_file = await asyncio.to_thread(genai.get_file, video_file.name)
    if video_file.state.name != "ACTIVE":
        raise RuntimeError(f"File processing failed: {video_file.state.name}")


def _convert_mss_to_seconds(val: float) -> float:
    minutes = int(val)
    frac = val - minutes
    seconds = round(frac * 100)
    return minutes * 60 + seconds


def _parse_response(text: str, video_duration: float = 0) -> dict:
    """Parse Gemini response into {segments, effects}."""
    text = text.strip()

    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        text = "\n".join(lines)

    # Try parsing as JSON object with segments/effects
    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Find JSON object or array
        obj_start = text.find("{")
        obj_end = text.rfind("}")
        arr_start = text.find("[")
        if obj_start != -1 and obj_end != -1 and (arr_start == -1 or obj_start < arr_start):
            try:
                data = json.loads(text[obj_start:obj_end + 1])
            except json.JSONDecodeError:
                pass

        # Fallback: try as array (old format)
        if data is None and arr_start != -1:
            arr_end = text.rfind("]")
            if arr_end != -1:
                try:
                    arr = json.loads(text[arr_start:arr_end + 1])
                    if isinstance(arr, list):
                        data = {"segments": arr, "effects": []}
                except json.JSONDecodeError:
                    pass

            # Truncated salvage
            if data is None:
                partial = text[arr_start:]
                for i in range(len(partial) - 1, 0, -1):
                    if partial[i] == "}":
                        try:
                            arr = json.loads(partial[:i + 1] + "]")
                            data = {"segments": arr, "effects": []}
                            log.info("Salvaged %d items from truncated response", len(arr))
                            break
                        except json.JSONDecodeError:
                            continue

    if not data:
        log.error("Failed to parse response: %s", text[:500])
        return {"segments": [], "effects": []}

    # Normalize: if it's a list, wrap it
    if isinstance(data, list):
        data = {"segments": data, "effects": []}

    # Parse segments
    raw_segments = data.get("segments", [])
    segments = []
    for s in raw_segments:
        if not isinstance(s, dict):
            continue
        start = s.get("start") or s.get("start_sec")
        end = s.get("end") or s.get("end_sec")
        if start is None or end is None:
            continue
        try:
            start, end = float(start), float(end)
        except (TypeError, ValueError):
            continue
        if end <= start or start < 0:
            continue
        segments.append({
            "start": start,
            "end": end,
            "type": str(s.get("type", "action")),
            "note": str(s.get("note", s.get("description", ""))),
        })

    segments.sort(key=lambda x: x["start"])

    # Parse effects
    raw_effects = data.get("effects", [])
    effects = []
    for e in raw_effects:
        if not isinstance(e, dict):
            continue
        at = e.get("at")
        if at is None:
            continue
        try:
            at = float(at)
        except (TypeError, ValueError):
            continue
        effects.append({
            "at": at,
            "duration": float(e.get("duration", 1.5)),
            "type": str(e.get("type", "zoom_slowmo")),
            "note": str(e.get("note", "")),
        })

    effects.sort(key=lambda x: x["at"])

    # Detect M.SS format on segments
    if segments and video_duration > 60:
        max_ts = max(s["end"] for s in segments)
        if max_ts < video_duration * 0.1:
            log.warning("Detected M.SS format (max=%.1f, dur=%.0f), converting...", max_ts, video_duration)
            for s in segments:
                s["start"] = _convert_mss_to_seconds(s["start"])
                s["end"] = _convert_mss_to_seconds(s["end"])
                if s["end"] <= s["start"]:
                    s["end"] = s["start"] + 5.0
            for e in effects:
                e["at"] = _convert_mss_to_seconds(e["at"])
            segments.sort(key=lambda x: x["start"])
            effects.sort(key=lambda x: x["at"])

    log.info("Parsed %d segments, %d effects", len(segments), len(effects))
    seg_types = Counter(s["type"] for s in segments)
    fx_types = Counter(e["type"] for e in effects)
    log.info("Segment types: %s | Effect types: %s", dict(seg_types), dict(fx_types))

    return {"segments": segments, "effects": effects}
