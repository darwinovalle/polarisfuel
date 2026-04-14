class ProviderError(Exception):
    """Base class for external provider errors."""


class ProviderTimeoutError(ProviderError):
    """Raised when provider request times out."""


class ProviderBadResponseError(ProviderError):
    """Raised when provider returns malformed or unexpected data."""


class ProviderUnavailableError(ProviderError):
    """Raised when provider is unavailable after retries."""