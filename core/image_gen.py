"""Image generation via Gemini (Imagen) and Flux."""

import io
import logging
import asyncio
import base64
from pathlib import Path

import google.generativeai as genai
from PIL import Image

from config import settings

log = logging.getLogger(__name__)

genai.configure(api_key=settings.gemini_api_key)


async def generate_image(prompt: str, model: str = "gemini") -> bytes | None:
    """Generate image from text prompt. Returns PNG bytes or None."""
    if model == "flux":
        return await _generate_flux(prompt)
    elif model == "gemini_pro":
        return await _generate_gemini(prompt, model_name="gemini-2.0-flash")
    else:
        return await _generate_gemini(prompt, model_name="gemini-2.0-flash")


async def edit_image(image_bytes: bytes, prompt: str, model: str = "gemini") -> bytes | None:
    """Edit image based on text instruction. Returns PNG bytes or None."""
    return await _edit_gemini(image_bytes, prompt)


async def _generate_gemini(prompt: str, model_name: str = "gemini-2.0-flash") -> bytes | None:
    """Use Gemini's native image generation."""
    try:
        model = genai.GenerativeModel(model_name)
        response = await asyncio.to_thread(
            model.generate_content,
            f"Generate an image: {prompt}",
            generation_config=genai.GenerationConfig(
                response_mime_type="image/png",
            ),
        )

        # Extract image from response
        for part in response.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                return part.inline_data.data

        log.warning("Gemini returned no image parts for prompt: %s", prompt[:100])
        return None
    except Exception as e:
        log.error("Gemini image gen failed: %s", e)
        return None


async def _edit_gemini(image_bytes: bytes, prompt: str) -> bytes | None:
    """Use Gemini to edit an image based on instruction."""
    try:
        # Save temp image for upload
        tmp = settings.temp_dir / "edit_input.png"
        img = Image.open(io.BytesIO(image_bytes))
        img.save(tmp, "PNG")

        uploaded = await asyncio.to_thread(genai.upload_file, str(tmp), mime_type="image/png")

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = await asyncio.to_thread(
            model.generate_content,
            [uploaded, f"Edit this image: {prompt}. Return the edited image."],
            generation_config=genai.GenerationConfig(
                response_mime_type="image/png",
            ),
        )

        try:
            await asyncio.to_thread(genai.delete_file, uploaded.name)
        except Exception:
            pass
        tmp.unlink(missing_ok=True)

        for part in response.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                return part.inline_data.data

        return None
    except Exception as e:
        log.error("Gemini image edit failed: %s", e)
        return None


async def _generate_flux(prompt: str) -> bytes | None:
    """Generate image via Flux (Hugging Face Inference API — free)."""
    import aiohttp

    hf_token = settings.hf_token
    if not hf_token:
        log.warning("HF_TOKEN not set, falling back to Gemini")
        return await _generate_gemini(prompt)

    url = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {hf_token}"}
    payload = {"inputs": prompt}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status == 200:
                    return await resp.read()
                else:
                    text = await resp.text()
                    log.error("Flux API error %d: %s", resp.status, text[:200])
                    return None
    except Exception as e:
        log.error("Flux generation failed: %s", e)
        return None
