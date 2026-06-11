class CruditConfigError(Exception):
    """Raised at registration time when the ListConfig is invalid."""


class CruditForbidden(Exception):
    """Raised when a permission check fails."""


class CruditNotFound(Exception):
    """Raised by service-layer functions when a target object does not exist."""


class CruditValidationError(Exception):
    """Raised by service-layer functions when input is invalid (missing path
    parameter, malformed body, etc.). Endpoints translate it to HTTP 400/422.

    ``fields`` optionally maps field names to error messages so callers can
    surface field-level errors (e.g. ``{"ids": ["IDs not found: [3]"]}``).
    """

    def __init__(self, message: str, *, fields: dict[str, list[str]] | None = None):
        super().__init__(message)
        self.message = message
        self.fields = fields or {}
