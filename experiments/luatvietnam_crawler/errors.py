"""Typed failures for the experimental crawler."""


class CrawlerError(RuntimeError):
    """Base error surfaced by the crawler CLI."""


class UnsupportedUrlError(CrawlerError):
    """Raised when a URL is outside the approved LuatVietnam host."""


class PageBlockedError(CrawlerError):
    """Raised when the remote site returns a challenge or block page."""


class SafetyPolicyError(CrawlerError):
    """Raised when a local quota, cooldown, or run lock blocks a request."""


class ParseError(CrawlerError):
    """Raised when required search or document content cannot be parsed."""


class ContentUnavailableError(ParseError):
    """Raised when the detail page explicitly says full text is unavailable."""
