"""Gemini video analyzer — finds moments matching user instruction."""

import json
import logging
import asyncio
import subprocess
import time as _time
from pathlib import Path

import google.generativeai as genai

from config import settings

# ffmpeg from imageio_ffmpeg (bundled with moviepy)
try:
    from imageio_ffmpeg import get_ffmpeg_exe
    FFMPEG = get_ffmpeg_exe()
except ImportError:
    FFMPEG = "ffmpeg"

log = logging.getLogger(__name__)

genai.configure(api_key=settings.gemini_api_key)

SYSTEM_PROMPT = """You are a professional gameplay clip editor AI.

You watch gameplay screen recordings and find EVERY moment matching the user's request.
You return timestamps in seconds with precision.

CRITICAL RULES:
1. Watch the ENTIRE video. Don't skip parts.
2. Timestamps must be REAL video time in seconds (e.g., 45.0, 67.5, 132.0)
3. A 3-minute video has moments between 0 and 180 seconds. Use the full range.
4. Find ALL matching moments, not just the first few.
5. Follow the user's instruction EXACTLY — if they say "every shot", find EVERY shot.

Return ONLY a JSON array (no markdown, no text, no commentary):
[
  {
    "start_sec": <float — 0.5s BEFORE the action starts>,
    "end_sec": <float — 0.3s AFTER the action ends>,
    "description": "<3-8 word TikTok caption in the same language as instruction>",
    "intensity": <int 1-10>,
    "moment_type": "<kill|hit|dodge|fail|funny|clutch|other>"
  }
]

Each moment should be 1.5-4 seconds long. No overlapping moments.
If nothing matches, return []"""


def _get_duration(path: str) -> float:
    """Get video duration in seconds via ffprobe."""
    try:
        cmd = [FFMPEG.replace("ffmpeg", "ffprobe") if "ffprobe" not in FFMPEG else FFMPEG,
               "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", path]
        # Try ffprobe next to ffmpeg
        ffprobe = str(Path(FFMPEG).parent / "ffprobe.exe") if Path(FFMPEG).parent != Path(FFMPEG) else "ffprobe"
        if not Path(ffprobe).exists():
            ffprobe = "ffprobe"
        cmd[0] = ffprobe
        r = subprocess.run(cmd, capture_output=True, timeout=10)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


async def analyze_video(video_path: str, instruction: str) -> list[dict]:
    """Upload video to Gemini and get moment timestamps."""
    size_mb = Path(video_path).stat().st_size / (1024 * 1024)
    video_duration = await asyncio.to_thread(_get_duration, video_path)
    log.info("Uploading video to Gemini: %s (%.1fMB, %.0fs)", video_path, size_mb, video_duration)

    # Compress large videos to reduce Gemini token usage
    # 1 fps 480p keeps enough visual info for timestamp detection
    upload_path = video_path
    compressed = None
    if size_mb > 50:
        compressed = str(Path(video_path).with_suffix(".analysis.mp4"))
        t_comp = _time.monotonic()
        log.info("Compressing for analysis: %s → 1fps 480p", video_path)
        ok = await asyncio.to_thread(_compress_for_analysis, video_path, compressed)
        if ok:
            comp_mb = Path(compressed).stat().st_size / (1024 * 1024)
            log.info("Compressed in %ds: %.1fMB → %.1fMB",
                     int(_time.monotonic() - t_comp), size_mb, comp_mb)
            upload_path = compressed
        else:
            log.warning("Compression failed, uploading original")
            compressed = None

    # Upload file (blocking — run in thread)
    t0 = _time.monotonic()
    video_file = await asyncio.to_thread(
        genai.upload_file, upload_path, mime_type="video/mp4"
    )
    upload_sec = int(_time.monotonic() - t0)
    log.info("Upload complete in %ds, waiting for processing...", upload_sec)

    # Wait for file to be processed
    await _wait_for_file(video_file)

    log.info("File ready, analyzing with instruction: %s", instruction)

    model = genai.GenerativeModel(
        "gemini-2.5-flash",
        system_instruction=SYSTEM_PROMPT,
    )

    dur_str = f"This video is {video_duration:.0f} seconds long. " if video_duration > 0 else ""
    dur_max = f"ALL timestamps MUST be between 0 and {video_duration:.0f}. " if video_duration > 0 else ""
    prompt = (
        f"USER REQUEST: {instruction}\n\n"
        f"{dur_str}"
        "Watch this gameplay video from start to end. "
        "Find EVERY moment that matches the user's request above. "
        f"{dur_max}"
        "Return timestamps as real video seconds. "
        "Return ONLY a JSON array — no markdown fences, no text before or after."
    )

    response = await asyncio.to_thread(
        model.generate_content,
        [video_file, prompt],
        generation_config=genai.GenerationConfig(
            temperature=0.2,
            max_output_tokens=65536,
        ),
    )
    resp_text = response.text or ""
    finish = response.candidates[0].finish_reason if response.candidates else "UNKNOWN"
    log.info("Gemini response: %d chars, finish_reason=%s", len(resp_text), finish)
    if len(resp_text) < 2000:
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

    return _parse_moments(resp_text)


def _compress_for_analysis(input_path: str, output_path: str) -> bool:
    """Compress video to 1fps 480p for Gemini analysis — drastically reduces tokens."""
    try:
        cmd = [
            FFMPEG, "-y", "-i", input_path,
            "-vf", "fps=5,scale=-2:360",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32",
            "-an",  # no audio needed for analysis
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=180)
        if result.returncode != 0:
            log.error("ffmpeg failed: %s", result.stderr[-500:].decode(errors="replace"))
            return False
        return Path(output_path).exists() and Path(output_path).stat().st_size > 0
    except Exception as e:
        log.error("Compression error: %s", e)
        return False


async def _wait_for_file(video_file, timeout: int = 300):
    """Wait for Gemini to finish processing the uploaded file."""
    elapsed = 0
    while video_file.state.name == "PROCESSING":
        if elapsed >= timeout:
            raise TimeoutError("Gemini file processing timed out")
        await asyncio.sleep(3)
        elapsed += 3
        video_file = await asyncio.to_thread(genai.get_file, video_file.name)

    if video_file.state.name != "ACTIVE":
        raise RuntimeError(f"File processing failed: {video_file.state.name}")


def _parse_moments(text: str) -> list[dict]:
    """Extract JSON array from Gemini response."""
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last line (```json and ```)
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        moments = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON array in the text
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            try:
                moments = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                log.error("Failed to parse Gemini response: %s", text[:500])
                return []
        elif start != -1:
            # Truncated response — try to salvage complete objects
            log.warning("Truncated JSON response, attempting salvage...")
            partial = text[start:]
            # Find last complete object (ends with })
            last_brace = partial.rfind("}")
            if last_brace > 0:
                try:
                    moments = json.loads(partial[:last_brace + 1] + "]")
                except json.JSONDecodeError:
                    log.error("Salvage failed: %s", text[:500])
                    return []
            else:
                log.error("No complete objects in truncated response: %s", text[:500])
                return []
        else:
            log.error("No JSON array found in Gemini response: %s", text[:500])
            return []

    if not isinstance(moments, list):
        return []

    # Validate and clean
    valid = []
    for m in moments:
        if not isinstance(m, dict):
            continue
        start = m.get("start_sec")
        end = m.get("end_sec")
        if start is None or end is None:
            continue
        try:
            start = float(start)
            end = float(end)
        except (TypeError, ValueError):
            continue
        if end <= start or start < 0:
            continue
        valid.append({
            "start_sec": start,
            "end_sec": end,
            "description": str(m.get("description", "")),
            "intensity": min(10, max(1, int(m.get("intensity", 5)))),
            "moment_type": str(m.get("moment_type", "other")),
        })

    valid.sort(key=lambda x: x["start_sec"])
    log.info("Parsed %d valid moments from Gemini", len(valid))
    return valid


def _guess_mime(path: str) -> str:
    ext = Path(path).suffix.lower()
    mime_map = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
    }
    return mime_map.get(ext, "video/mp4")
