"""Shared base error for text-generation adapters.

Kept in ``src/shared`` so the retrieval layer can ``except`` it without importing
``src/infrastructure`` (which the dependency-direction test forbids). Concrete
infrastructure adapters raise subclasses of this base.
"""

from __future__ import annotations


class TextGenerationError(RuntimeError):
    """Base class for text-generation adapter failures."""
