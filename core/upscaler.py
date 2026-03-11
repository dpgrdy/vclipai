"""Image upscaling — 2x resolution enhancement."""

import io
import logging
import asyncio

from PIL import Image, ImageFilter

log = logging.getLogger(__name__)


async def upscale_image(image_bytes: bytes, scale: int = 2) -> bytes | None:
    """Upscale image by given factor. Returns PNG bytes."""
    try:
        return await asyncio.to_thread(_upscale_sync, image_bytes, scale)
    except Exception as e:
        log.error("Upscale failed: %s", e)
        return None


def _upscale_sync(image_bytes: bytes, scale: int) -> bytes:
    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size

    # Upscale with LANCZOS (high quality)
    new_size = (w * scale, h * scale)
    upscaled = img.resize(new_size, Image.LANCZOS)

    # Sharpen to recover details
    upscaled = upscaled.filter(ImageFilter.SHARPEN)

    # Slight unsharp mask for extra clarity
    upscaled = upscaled.filter(ImageFilter.UnsharpMask(radius=1.5, percent=80, threshold=2))

    buf = io.BytesIO()
    upscaled.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
