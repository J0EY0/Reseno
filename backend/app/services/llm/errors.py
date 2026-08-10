class LlmRequestError(RuntimeError):
    """Provider/runtime failure with optional transport status for safe routing.

    The Agent runtime uses ``status_code`` only to classify a narrow native-file
    incompatibility. Authentication, throttling, timeout, and server failures
    must never be retried as attachment-format fallbacks.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class LlmTimeoutError(LlmRequestError):
    """A provider connection or stream stopped making progress in time."""
