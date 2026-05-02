class CruditConfigError(Exception):
    """Raised at registration time when the ListConfig is invalid."""


class CruditForbidden(Exception):
    """Raised when a permission check fails."""


class CruditNotFound(Exception):
    """Raised by service-layer functions when a target object does not exist."""


class CruditValidationError(Exception):
    """Raised by service-layer functions when input is invalid (missing path
    parameter, malformed body, etc.). Endpoints translate it to HTTP 400."""
