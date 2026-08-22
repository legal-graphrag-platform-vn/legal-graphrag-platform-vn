"""Canonical lookup regressions for named legal references."""

from __future__ import annotations

import asyncio

from resolution.canonical_lookup import Neo4jCanonicalLookup, _build_query
from resolution.models import ExplicitReference


class _ImmediateRunner:
    async def run(self, call):
        return call()


class _LookupRepo:
    def __init__(self, rows):
        self._rows = rows

    def lookup(self, reference):
        return self._rows


def _article_row(*, document_id: str, number: str, title: str) -> dict:
    return {
        "document_id": document_id,
        "document_number": number,
        "document_title": title,
        "doc_type": "Law",
        "issuer_name": "Quốc hội",
        "legal_status": "ACTIVE",
        "article_id": f"{document_id}_art16",
        "article_number": "16",
        "clause_id": None,
        "clause_number": None,
        "point_id": None,
        "point_label": None,
    }


def test_named_law_keeps_only_version_family_titles() -> None:
    lookup = Neo4jCanonicalLookup(
        _LookupRepo(
            [
                _article_row(
                    document_id="l_04_2011",
                    number="04/2011/QH13",
                    title="Nghị định hướng dẫn Luật Doanh nghiệp",
                ),
                _article_row(
                    document_id="ldn_2014",
                    number="68/2014/QH13",
                    title="Luật Doanh nghiệp 2014, số 68/2014/QH13",
                ),
                _article_row(
                    document_id="ldn_2020",
                    number="59/2020/QH14",
                    title="LUẬT DOANH NGHIỆP 2020, SỐ 59/2020/QH14",
                ),
                _article_row(
                    document_id="ldnn_2003",
                    number="14/2003/QH11",
                    title="Luật Doanh nghiệp Nhà nước năm 2003",
                ),
            ]
        ),
        _ImmediateRunner(),
    )

    candidates = asyncio.run(
        lookup.lookup(
            ExplicitReference(law_name="Luật Doanh nghiệp", article_number="16")
        )
    )

    assert [candidate.document_id for candidate in candidates] == [
        "ldn_2014",
        "ldn_2020",
    ]


def test_canonical_lookup_excludes_documents_without_canonical_id() -> None:
    query, _ = _build_query(
        ExplicitReference(law_name="Luật Doanh nghiệp", article_number="16")
    )

    assert "document.id IS NOT NULL" in query
    assert "document.title) STARTS WITH" in query
    assert "document.title) CONTAINS" not in query
