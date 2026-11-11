"""
Upload validation and sanitisation with Pillow.

- Enforces the size limit before decoding.
- Detects the real format from the file contents (the client-supplied
  content type and filename are never trusted).
- Checks the format against ALLOWED_IMAGE_TYPES.
- Fully decodes the image to reject corrupt/truncated files and
  decompression bombs.
- Re-encodes pixel data only, which drops EXIF (including GPS), XMP, ICC
  and any other embedded metadata. EXIF orientation is applied first so the
  sanitised image is displayed the right way up.
"""

import hashlib
import io
import warnings
from dataclasses import dataclass

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError

from .exceptions import CorruptImageError, ImageTooLargeError, UnsupportedImageTypeError

# Pillow format name -> (MIME type, file extension)
FORMAT_TO_MIME = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}


@dataclass(frozen=True)
class SanitizedImage:
    content: bytes
    content_type: str
    extension: str
    width: int
    height: int
    sha256: str

    @property
    def size(self) -> int:
        return len(self.content)


def _read_limited(uploaded_file, max_bytes: int) -> bytes:
    declared_size = getattr(uploaded_file, "size", None)
    if declared_size is not None and declared_size > max_bytes:
        raise ImageTooLargeError(f"declared size {declared_size} > {max_bytes}")
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    data = uploaded_file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ImageTooLargeError(f"read size > {max_bytes}")
    if not data:
        raise CorruptImageError("empty upload")
    return data


def _strip_metadata(image: Image.Image) -> Image.Image:
    """Return a new image containing only pixel data (plus palette if any)."""
    clean = Image.frombytes(image.mode, image.size, image.tobytes())
    if image.mode == "P" and image.getpalette():
        clean.putpalette(image.getpalette())
    return clean


def validate_and_sanitize(uploaded_file) -> SanitizedImage:
    """
    Validate an uploaded image and return a metadata-free re-encoded copy.

    Raises ImageTooLargeError, UnsupportedImageTypeError or CorruptImageError.
    """
    max_bytes = settings.MAX_UPLOAD_SIZE_BYTES
    data = _read_limited(uploaded_file, max_bytes)
    Image.MAX_IMAGE_PIXELS = settings.MAX_IMAGE_PIXELS

    with warnings.catch_warnings():
        # Treat decompression-bomb warnings as hard errors.
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            probe = Image.open(io.BytesIO(data))
            image_format = probe.format
            probe.verify()
        except UnidentifiedImageError as exc:
            raise UnsupportedImageTypeError("unidentified image format") from exc
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ImageTooLargeError("pixel count exceeds limit") from exc
        except Exception as exc:
            raise CorruptImageError(f"verify failed: {type(exc).__name__}") from exc

        mime_ext = FORMAT_TO_MIME.get(image_format)
        if mime_ext is None or mime_ext[0] not in settings.ALLOWED_IMAGE_TYPES:
            raise UnsupportedImageTypeError(f"format {image_format!r} not allowed")
        content_type, extension = mime_ext

        try:
            # verify() leaves the image unusable; reopen and fully decode.
            image = Image.open(io.BytesIO(data))
            image.load()
            image = ImageOps.exif_transpose(image)
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ImageTooLargeError("pixel count exceeds limit") from exc
        except Exception as exc:
            raise CorruptImageError(f"decode failed: {type(exc).__name__}") from exc

    if image_format == "JPEG" and image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    clean = _strip_metadata(image)
    buffer = io.BytesIO()
    save_kwargs = {"quality": 90} if image_format in ("JPEG", "WEBP") else {}
    if image_format == "PNG" and "transparency" in image.info:
        save_kwargs["transparency"] = image.info["transparency"]
    clean.save(buffer, format=image_format, **save_kwargs)
    content = buffer.getvalue()

    return SanitizedImage(
        content=content,
        content_type=content_type,
        extension=extension,
        width=clean.width,
        height=clean.height,
        sha256=hashlib.sha256(content).hexdigest(),
    )
