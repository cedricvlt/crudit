class CruditConfigError(Exception):
    """Raised at registration time when the ListConfig is invalid."""


class CruditForbidden(Exception):
    """Raised when a permission check fails."""
