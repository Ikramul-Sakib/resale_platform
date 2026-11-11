"""
Recognition pipeline exceptions.

Every exception carries a ``user_message`` that is safe to show to end users
and store in ``Scan.error_message``. Internal details stay in logs only.
``retryable`` tells the background task whether a retry may succeed.
"""


class RecognitionError(Exception):
    """Base class for all recognition pipeline errors."""

    user_message = "We couldn't identify this item. Please try again."
    retryable = False

    def __init__(self, detail: str = "", user_message: str | None = None):
        super().__init__(detail or self.user_message)
        if user_message:
            self.user_message = user_message


# --- Upload / image validation (never retryable) ---------------------------


class ImageValidationError(RecognitionError):
    """The uploaded file is not an acceptable image."""

    user_message = "The uploaded file is not a valid image."


class UnsupportedImageTypeError(ImageValidationError):
    user_message = "Unsupported file type. Please upload a JPEG, PNG, or WebP image."


class ImageTooLargeError(ImageValidationError):
    user_message = "The image is too large. Please upload a smaller file."


class CorruptImageError(ImageValidationError):
    user_message = "The image could not be read. It may be corrupt or incomplete."


# --- Provider errors --------------------------------------------------------


class RecognitionNotConfiguredError(RecognitionError):
    """No recognition provider is configured; never pretend recognition works."""

    user_message = "Image recognition is not available right now."


class ProviderError(RecognitionError):
    """The provider failed or returned an unusable result."""

    user_message = "The recognition service failed to process this image."


class ProviderUnavailableError(ProviderError):
    """Transient provider failure (e.g. 5xx, connection reset)."""

    user_message = "The recognition service is temporarily unavailable. Please try again later."
    retryable = True


class ProviderTimeoutError(ProviderUnavailableError):
    """The provider did not respond within the configured timeout."""

    user_message = "The recognition service took too long to respond. Please try again later."
