"""Data contracts local to the LuatVietnam experiment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


PROVIDER_REFERENCE_CONTRACT_VERSION = "provider-reference-mention-v1"


@dataclass(frozen=True, slots=True)
class ProviderReferenceMention:
    """Provider evidence for one bracket marker in canonical source text."""

    provider_source_document_id: str
    provider_source_item_id: str | None
    provider_target_document_id: str | None
    provider_target_item_ids: tuple[str, ...]
    provider_relation_id: str | None
    provider_link_type: Literal["CHANGE_CONTENT", "REFERENCE", "UNKNOWN"]
    citation_text: str
    source_char_start: int
    source_char_end: int
    provider_href: str | None
    contract_version: str = PROVIDER_REFERENCE_CONTRACT_VERSION
    provider: str = "luatvietnam"

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "provider": self.provider,
            "provider_source_document_id": self.provider_source_document_id,
            "provider_source_item_id": self.provider_source_item_id,
            "provider_target_document_id": self.provider_target_document_id,
            "provider_target_item_ids": list(self.provider_target_item_ids),
            "provider_relation_id": self.provider_relation_id,
            "provider_link_type": self.provider_link_type,
            "citation_text": self.citation_text,
            "source_char_start": self.source_char_start,
            "source_char_end": self.source_char_end,
            "provider_href": self.provider_href,
        }


@dataclass(frozen=True, slots=True)
class ProviderItemSpan:
    """Exact canonical-text span of one LuatVietnam ``demuc`` item."""

    provider_item_id: str
    source_char_start: int
    source_char_end: int


@dataclass(frozen=True, slots=True)
class SearchDocument:
    title: str
    url: str
    external_id: str
    detail_variant: str
    source_kind: str


@dataclass(frozen=True, slots=True)
class SearchPageMetadata:
    total_results: int
    page_size: int
    current_page: int
    total_pages: int
    visible_page_indexes: tuple[int, ...]
    next_page: int | None
    document_types: tuple[str, ...]
    issuers_raw: str | None
    fields: tuple[str, ...]
    language: str | None
    summary_raw: str

    def as_dict(self) -> dict[str, object]:
        return {
            "total_results": self.total_results,
            "page_size": self.page_size,
            "current_page": self.current_page,
            "total_pages": self.total_pages,
            "visible_page_indexes": list(self.visible_page_indexes),
            "next_page": self.next_page,
            "document_types": list(self.document_types),
            "issuers_raw": self.issuers_raw,
            "fields": list(self.fields),
            "language": self.language,
            "summary_raw": self.summary_raw,
        }


@dataclass(frozen=True, slots=True)
class DetailMetadata:
    """Metadata visible on a LuatVietnam document detail page."""

    external_id: str
    title: str
    number: str
    document_type_raw: str | None
    doc_type: str
    issuer_name: str | None
    issuer_branch: str
    signer: str | None
    abstract: str | None
    issued_date: date | None
    application_raw: str | None
    effective_from: date | None
    effective_to_raw: str | None
    effective_to: date | None
    status_raw: str | None
    legal_status: str | None
    gazette_number_raw: str | None
    gazette_number: str | None
    gazette_date_raw: str | None
    gazette_date: date | None
    fields: tuple[str, ...]
    page_updated_at: datetime | None
    og_url: str | None
    og_title: str | None
    og_description: str | None
    og_image: str | None
    html_full_text_available: bool
    article_count: int
    content_character_count: int
    reference_marker_count: int
    content_serializer_version: str
    source_url: str

    def as_dict(self) -> dict[str, object]:
        return {
            "external_id": self.external_id,
            "title": self.title,
            "number": self.number,
            "document_type_raw": self.document_type_raw,
            "doc_type": self.doc_type,
            "issuer_name": self.issuer_name,
            "issuer_branch": self.issuer_branch,
            "signer": self.signer,
            "abstract": self.abstract,
            "issued_date": self.issued_date.isoformat() if self.issued_date else None,
            "application_raw": self.application_raw,
            "effective_from": (
                self.effective_from.isoformat() if self.effective_from else None
            ),
            "effective_to_raw": self.effective_to_raw,
            "effective_to": self.effective_to.isoformat()
            if self.effective_to
            else None,
            "status_raw": self.status_raw,
            "legal_status": self.legal_status,
            "gazette_number_raw": self.gazette_number_raw,
            "gazette_number": self.gazette_number,
            "gazette_date_raw": self.gazette_date_raw,
            "gazette_date": self.gazette_date.isoformat()
            if self.gazette_date
            else None,
            "fields": list(self.fields),
            "page_updated_at": (
                self.page_updated_at.isoformat() if self.page_updated_at else None
            ),
            "open_graph": {
                "url": self.og_url,
                "title": self.og_title,
                "description": self.og_description,
                "image": self.og_image,
            },
            "content": {
                "html_full_text_available": self.html_full_text_available,
                "article_count": self.article_count,
                "character_count": self.content_character_count,
                "reference_marker_count": self.reference_marker_count,
                "serializer_version": self.content_serializer_version,
            },
            "source_url": self.source_url,
        }


@dataclass(frozen=True, slots=True)
class CrawledDocument:
    raw_doc_code: str
    candidate_graph_id: str
    external_id: str
    title: str
    number: str
    doc_type: str
    normative: bool
    issuer_name: str | None
    issuer_branch: str
    issued_date: date | None
    effective_from: date | None
    effective_to: date | None
    status: str | None
    legal_status: str | None
    source_url: str
    source_text: str
    article_count: int
    reference_marker_count: int
    content_serializer_version: str
    provider_references: tuple[ProviderReferenceMention, ...] = ()

    def metadata(self) -> dict[str, object]:
        return {
            "raw_doc_code": self.raw_doc_code,
            "candidate_graph_id": self.candidate_graph_id,
            "external_id": self.external_id,
            "title": self.title,
            "number": self.number,
            "doc_type": self.doc_type,
            "normative": self.normative,
            "issuer_name": self.issuer_name,
            "issuer_branch": self.issuer_branch,
            "issued_date": self.issued_date.isoformat() if self.issued_date else None,
            "effective_from": (
                self.effective_from.isoformat() if self.effective_from else None
            ),
            "effective_to": self.effective_to.isoformat()
            if self.effective_to
            else None,
            "status": self.status,
            "legal_status": self.legal_status,
            "source_url": self.source_url,
            "source_provider": "luatvietnam.vn",
            "experimental": True,
            "content": {
                "html_full_text_available": True,
                "article_count": self.article_count,
                "character_count": len(self.source_text),
                "reference_marker_count": self.reference_marker_count,
                "provider_reference_count": len(self.provider_references),
                "serializer_version": self.content_serializer_version,
            },
        }
