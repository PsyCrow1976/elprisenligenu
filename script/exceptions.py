"""Errors raised by the price client."""


class PriceError(Exception):
    """Base error for all client failures."""


class ConfigError(PriceError):
    """Raised when required settings are missing or invalid."""


class ApiError(PriceError):
    """Raised when an upstream API returns an error or unexpected payload."""

    def __init__(self, message, *, status_code=None, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body
