from src.pipeline.extraction.structural_context import (
    DocumentRegistry,
    StructuralRegistry,
)
from src.pipeline.extraction.structural_references import StructuralReferenceResolver
from src.pipeline.parser.hierarchy_parser import canonicalize_source_text, parse_text
from src.pipeline.parser.models import DocumentInfo


def _document() -> DocumentInfo:
    return DocumentInfo(
        id="ldn_2020", title="Luật", number="59/2020/QH14", doc_type="Law"
    )


def test_resolves_multi_target_reference_atomically_and_preserves_d_dd() -> None:
    text = """Điều 1. Trách nhiệm
1. Khoản
a) Nghĩa vụ a;
b) Nghĩa vụ b;
d) Nghĩa vụ d;
đ) Nghĩa vụ đ;
c) Phải thực hiện các điểm a, b, d và đ khoản này.
"""
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    references = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )

    assert len(references) == 1
    reference = references[0]
    assert reference.status == "RESOLVED"
    assert reference.target_unit_ids == (
        "ldn_2020_art1_cl1_pa",
        "ldn_2020_art1_cl1_pb",
        "ldn_2020_art1_cl1_pd",
        "ldn_2020_art1_cl1_pdd",
    )
    canonical = canonicalize_source_text(text)
    mention = reference.mention
    assert (
        canonical[mention.source_char_start : mention.source_char_end]
        == mention.raw_text
    )


def test_missing_one_target_rejects_the_whole_reference() -> None:
    text = """Điều 1. Trách nhiệm
1. Khoản
a) Nghĩa vụ a;
c) Theo các điểm a và b khoản này.
"""
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    reference = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )[0]

    assert reference.status == "UNRESOLVED"
    assert reference.target_unit_ids == ()


def test_current_clause_self_reference_creates_no_edge() -> None:
    text = "Điều 1. Trách nhiệm\n1. Thực hiện theo khoản này."
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    reference = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )[0]

    assert reference.status == "SELF_REFERENCE"


def test_explicit_external_reference_never_falls_back_to_current_document() -> None:
    text = (
        "Điều 1. Chuyển tiếp\n1. Khoản\n"
        "a) Theo điểm m khoản 1 Điều 35 của Luật số 68/2014/QH13."
    )
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")
    document_registry = DocumentRegistry({"682014qh13": ("ldn_2014", "Law")})

    reference = StructuralReferenceResolver(
        registry,
        text,
        document_registry=document_registry,
    ).resolve_article(parsed.articles[0])[0]

    assert reference.status == "RESOLVED"
    assert reference.resolution_method == "ENTITY_LINKING"
    assert reference.target_unit_ids == ("ldn_2014_art35_cl1_pm",)


def test_unregistered_external_reference_is_ambiguous_not_local() -> None:
    text = (
        "Điều 1. Chuyển tiếp\n1. Khoản\n"
        "a) Theo điểm m khoản 1 Điều 35 của Luật số 83/2015/QH13."
    )
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    reference = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )[0]

    assert reference.status == "AMBIGUOUS"
    assert reference.resolution_method == "ENTITY_LINKING"
    assert reference.target_unit_ids == ()
