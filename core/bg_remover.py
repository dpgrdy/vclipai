"""Background removal using rembg (local, free)."""

import io
import logging
import asyncio

from PIL import Image

log = logging.getLogger(__name__)


async def remove_background(image_bytes: bytes) -> bytes | None:
    """Remove background from image. Returns PNG bytes with transparency."""
    try:
        result = await asyncio.to_thread(_remove_sync, image_bytes)
        return result
    except Exception as e:
        log.error("Background removal failed: %s", e)
        return None


def _remove_sync(image_bytes: bytes) -> bytes:
    from rembg import remove
    input_img = Image.open(io.BytesIO(image_bytes))
    output_img = remove(input_img)
    buf = io.BytesIO()
    output_img.save(buf, format="PNG")
    return buf.getvalue()
