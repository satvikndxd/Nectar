"""Domain error hierarchy.

These are framework-free: the API layer maps them to HTTP responses, and nothing in
this package knows that HTTP exists.
"""


class NiglasError(Exception):
    """Base class for every error Niglas raises deliberately."""


class DomainError(NiglasError):
    """A domain rule was violated (bad money arithmetic, illegal time window, ...)."""


class AuthorizationError(NiglasError):
    """A principal attempted something its roles do not permit."""
