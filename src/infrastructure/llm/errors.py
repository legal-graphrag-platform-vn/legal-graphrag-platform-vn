"""Typed failures for text-generation adapters."""

from __future__ import annotations


class TextGenerationError(RuntimeError):
    """Base class for text-generation adapter failures."""


class TextGenerationDependencyError(TextGenerationError):
    """A required SDK, network endpoint, or credential was unavailable."""


class TextGenerationOutputError(TextGenerationError):
    """The provider returned an empty or unusable payload."""
