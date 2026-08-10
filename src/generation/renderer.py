"""Deterministic Markdown renderer for structurally grounded answers."""

from __future__ import annotations

import re
from collections.abc import Mapping

from src.generation.models import AnswerCandidate, AnswerParagraph, GroundedStatement

_MARKDOWN_SPECIAL = re.compile(r"([\\`*_<>{}\[\]#])")


class DeterministicAnswerRenderer:
    """Render validated model text without generating or paraphrasing content."""

    def render(
        self,
        candidate: AnswerCandidate,
        citation_ordinals: Mapping[str, int],
    ) -> str:
        blocks: list[str] = []
        if candidate.direct_answer is not None:
            blocks.extend(
                self._render_paragraph(paragraph, citation_ordinals)
                for paragraph in candidate.direct_answer.paragraphs
            )
        for section in candidate.sections:
            blocks.append(f"## {self._escape(section.heading.strip())}")
            blocks.extend(
                self._render_paragraph(paragraph, citation_ordinals)
                for paragraph in section.paragraphs
            )
        if candidate.caveats:
            blocks.append("## Lưu ý")
            blocks.extend(
                self._render_paragraph(paragraph, citation_ordinals)
                for paragraph in candidate.caveats
            )
        return "\n\n".join(blocks)

    def _render_paragraph(
        self,
        paragraph: AnswerParagraph,
        citation_ordinals: Mapping[str, int],
    ) -> str:
        return " ".join(
            self._render_statement(statement, citation_ordinals)
            for statement in paragraph.statements
        )

    def _render_statement(
        self,
        statement: GroundedStatement,
        citation_ordinals: Mapping[str, int],
    ) -> str:
        citations = "".join(
            f"[{citation_ordinals[citation_id]}]"
            for citation_id in statement.citation_ids
        )
        return f"{self._escape(statement.text.strip())} {citations}"

    @staticmethod
    def _escape(value: str) -> str:
        return _MARKDOWN_SPECIAL.sub(r"\\\1", value)
