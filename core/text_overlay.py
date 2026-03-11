"""Text overlays for clips — TikTok style captions."""

import logging
from pathlib import Path

from moviepy import VideoClip, CompositeVideoClip, ImageClip
from PIL import Image, ImageDraw, ImageFont
import numpy as np

log = logging.getLogger(__name__)

# Try to find a bold font
FONT_PATHS = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def add_text_to_clip(clip: VideoClip, text: str) -> VideoClip:
    """Add TikTok-style text overlay to bottom third of clip."""
    if not text:
        return clip

    w, h = clip.size
    font_size = max(24, int(h * 0.04))  # ~4% of video height
    font = _get_font(font_size)

    # Create text image with outline
    text_img = _render_text_with_outline(
        text=text,
        font=font,
        max_width=int(w * 0.85),
        text_color=(255, 255, 255),
        outline_color=(0, 0, 0),
        outline_width=max(2, font_size // 12),
    )

    text_h, text_w = text_img.shape[:2]
    # Position: bottom third, centered horizontally
    x_pos = (w - text_w) // 2
    y_pos = int(h * 0.78)  # ~78% from top

    text_clip = (
        ImageClip(text_img)
        .with_duration(clip.duration)
        .with_position((x_pos, y_pos))
    )

    return CompositeVideoClip([clip, text_clip])


def _render_text_with_outline(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    text_color: tuple = (255, 255, 255),
    outline_color: tuple = (0, 0, 0),
    outline_width: int = 3,
) -> np.ndarray:
    """Render text with outline as RGBA numpy array."""
    # Word wrap
    lines = _wrap_text(text, font, max_width)
    line_text = "\n".join(lines)

    # Measure
    dummy_img = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy_img)
    bbox = draw.multiline_textbbox((0, 0), line_text, font=font)
    text_w = bbox[2] - bbox[0] + outline_width * 2 + 10
    text_h = bbox[3] - bbox[1] + outline_width * 2 + 10

    # Render
    img = Image.new("RGBA", (text_w, text_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    x, y = outline_width + 5, outline_width + 5

    # Draw outline
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx * dx + dy * dy <= outline_width * outline_width:
                draw.multiline_text(
                    (x + dx, y + dy), line_text, font=font,
                    fill=(*outline_color, 255), align="center",
                )

    # Draw text
    draw.multiline_text(
        (x, y), line_text, font=font,
        fill=(*text_color, 255), align="center",
    )

    return np.array(img)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Simple word wrap."""
    words = text.split()
    lines = []
    current = ""

    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)

    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines or [text]
