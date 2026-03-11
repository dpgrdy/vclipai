"""Video note (circle) editing — apply effects via ffmpeg."""

import asyncio
import logging
import uuid
from pathlib import Path

from config import settings

log = logging.getLogger(__name__)

# Effect → ffmpeg video filter
EFFECTS = {
    "bw": ("-vf", "hue=s=0"),
    "warm": ("-vf", "colorbalance=rs=0.15:gs=0.05:bs=-0.1"),
    "cool": ("-vf", "colorbalance=rs=-0.1:gs=0.0:bs=0.15"),
    "vintage": ("-vf", "curves=vintage,eq=saturation=0.7"),
    "speed2x": ("-filter:v", "setpts=0.5*PTS", "-filter:a", "atempo=2.0"),
    "slow": ("-filter:v", "setpts=2.0*PTS", "-filter:a", "atempo=0.5"),
    "reverse": ("-vf", "reverse", "-af", "areverse"),
    "sharp": ("-vf", "unsharp=5:5:1.5:5:5:0.5,eq=contrast=1.1:brightness=0.03"),
}


async def process_circle(input_path: Path, effect: str) -> Path | None:
    """Apply effect to video note file. Returns output path or None."""
    out = settings.temp_dir / f"circle_{uuid.uuid4().hex[:8]}.mp4"

    ef = EFFECTS.get(effect)
    if not ef:
        log.error("Unknown circle effect: %s", effect)
        return None

    # Build ffmpeg command
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        *ef,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out),
    ]

    # For speed/slow effects, audio filter is separate from video filter
    # For reverse, we need to handle no-audio case
    if effect in ("speed2x", "slow"):
        # Already handled in EFFECTS with separate -filter:v and -filter:a
        pass

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            log.error("ffmpeg circle failed (rc=%d): %s", proc.returncode, stderr.decode()[-500:])
            out.unlink(missing_ok=True)
            return None

        if not out.exists() or out.stat().st_size < 1000:
            log.error("ffmpeg circle output too small or missing")
            out.unlink(missing_ok=True)
            return None

        return out

    except asyncio.TimeoutError:
        log.error("ffmpeg circle timeout")
        out.unlink(missing_ok=True)
        return None
    except Exception as e:
        log.error("ffmpeg circle error: %s", e)
        out.unlink(missing_ok=True)
        return None
