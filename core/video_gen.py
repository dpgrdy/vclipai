"""Video generation — text-to-video and image-to-video via Gemini Veo."""

import io
import logging
import asyncio
import time
from pathlib import Path

import google.generativeai as genai

from config import settings

log = logging.getLogger(__name__)

genai.configure(api_key=settings.gemini_api_key)


async def generate_video_from_text(prompt: str) -> Path | None:
    """Generate video from text prompt using Gemini Veo."""
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")

        response = await asyncio.to_thread(
            model.generate_content,
            f"Generate a short video (3-5 seconds): {prompt}",
            generation_config=genai.GenerationConfig(
                response_mime_type="video/mp4",
            ),
        )

        for part in response.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                out = settings.temp_dir / f"gen_{int(time.time())}.mp4"
                out.write_bytes(part.inline_data.data)
                return out

        log.warning("No video in response for: %s", prompt[:100])
        return None
    except Exception as e:
        log.error("Video generation failed: %s", e)
        return None


async def generate_video_from_image(image_bytes: bytes, prompt: str) -> Path | None:
    """Generate video from image + prompt using Gemini."""
    try:
        from PIL import Image
        tmp_img = settings.temp_dir / "vid_input.png"
        img = Image.open(io.BytesIO(image_bytes))
        img.save(tmp_img, "PNG")

        uploaded = await asyncio.to_thread(genai.upload_file, str(tmp_img), mime_type="image/png")

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = await asyncio.to_thread(
            model.generate_content,
            [uploaded, f"Generate a short video based on this image: {prompt}"],
            generation_config=genai.GenerationConfig(
                response_mime_type="video/mp4",
            ),
        )

        try:
            await asyncio.to_thread(genai.delete_file, uploaded.name)
        except Exception:
            pass
        tmp_img.unlink(missing_ok=True)

        for part in response.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                out = settings.temp_dir / f"gen_{int(time.time())}.mp4"
                out.write_bytes(part.inline_data.data)
                return out

        return None
    except Exception as e:
        log.error("Image-to-video failed: %s", e)
        return None
