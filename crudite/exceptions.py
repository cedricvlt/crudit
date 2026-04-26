class CruditeConfigError(Exception):
    """Raised at registration time when the ListConfig is invalid."""


class CruditeForbidden(Exception):
    """Raised when a permission check fails."""
