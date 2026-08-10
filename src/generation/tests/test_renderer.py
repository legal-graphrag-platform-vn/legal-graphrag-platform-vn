from __future__ import annotations

from src.generation.models import (
    AnswerBlock,
    AnswerCandidate,
    AnswerParagraph,
    AnswerSection,
    GroundedStatement,
)
from src.generation.renderer import DeterministicAnswerRenderer


def _statement(statement_id: str, text: str, citations: list[str]) -> GroundedStatement:
    return GroundedStatement(
        statement_id=statement_id,
        text=text,
        citation_ids=citations,
    )


def test_renderer_joins_statements_into_paragraphs_without_paraphrasing() -> None:
    candidate = AnswerCandidate(
        direct_answer=AnswerBlock(
            paragraphs=[
                AnswerParagraph(
                    statements=[
                        _statement("s1", "Có.", ["src_a"]),
                        _statement("s2", "Quyền này có điều kiện.", ["src_b", "src_a"]),
                    ]
                )
            ]
        ),
        sections=[
            AnswerSection(
                heading="Quy định áp dụng",
                paragraphs=[
                    AnswerParagraph(
                        statements=[
                            _statement(
                                "s3", "Điều kiện được quy định riêng.", ["src_b"]
                            )
                        ]
                    )
                ],
            )
        ],
        confidence=0.9,
        cannot_answer=False,
    )

    rendered = DeterministicAnswerRenderer().render(
        candidate,
        {"src_a": 1, "src_b": 2},
    )

    assert rendered == (
        "Có. [1] Quyền này có điều kiện. [2][1]\n\n"
        "## Quy định áp dụng\n\nĐiều kiện được quy định riêng. [2]"
    )


def test_renderer_escapes_model_supplied_markdown() -> None:
    candidate = AnswerCandidate(
        direct_answer=AnswerBlock(
            paragraphs=[
                AnswerParagraph(
                    statements=[_statement("s1", "Nội dung *không* tự render", ["src"])]
                )
            ]
        ),
        confidence=0.9,
        cannot_answer=False,
    )

    assert DeterministicAnswerRenderer().render(candidate, {"src": 1}) == (
        r"Nội dung \*không\* tự render [1]"
    )
