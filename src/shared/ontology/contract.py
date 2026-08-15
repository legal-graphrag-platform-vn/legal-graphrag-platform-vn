"""Executable mirror of the canonical ontology contract.

``plans/legal_ontology.md`` is normative. All validators (write-time and
extraction-time) import constants from this module, which must carry the same
version and rules as that document.

Quy tắc cập nhật:
- Bump ONTOLOGY_VERSION (semver) mỗi khi thêm/xoá/sửa bất kỳ constant nào.
- Đồng thời cập nhật frozen-version assertion trong test_ontology_consistency.py.
- Mọi validator, payload builder, writer đều phải import từ module này —
  KHÔNG được hardcode string ontology ở nơi khác.
"""

from __future__ import annotations

from typing import Any


# ── Versioning ────────────────────────────────────────────────────────────────

# Phiên bản ontology hiện tại. Tăng PATCH khi thêm optional field/alias,
# tăng MINOR khi thêm loại node/relation mới, tăng MAJOR khi xoá/đổi tên.
ONTOLOGY_VERSION = "1.15.0"


# ── Synthetic Article Convention ──────────────────────────────────────────────

# Prefix số hiệu cho Synthetic Articles — tạo từ văn bản SOURCE_PRESERVED
# (Thông tư cũ dùng Roman outline I/, II/ thay vì cấu trúc Điều-Khoản chuẩn).
# Ví dụ: 'SP_1', 'SP_2', ...
# Synthetic Articles được gắn thẳng vào Document (không qua Chapter/Section).
# Field is_synthetic=True được set trong payload để downstream nhận biết.
# Xem: src/pipeline/pipeline/orchestrator.py → _synthetic_articles_from_unparsed
SYNTHETIC_ARTICLE_NUMBER_PREFIX = "SP_"


# ── Document metadata enums ───────────────────────────────────────────────────

# Loại văn bản quy phạm pháp luật theo Luật BHVBQPPL 2015.
# Thứ tự phân cấp: Constitution > Law/Ordinance > Decree/Resolution > Decision/Circular.
DOCUMENT_TYPES: set[str] = {
    "Constitution",       # Hiến pháp
    "Law",                # Luật / Bộ luật
    "Ordinance",          # Pháp lệnh
    "Resolution",         # Nghị quyết (QH/UBTVQH)
    "Decree",             # Nghị định
    "Decision",           # Quyết định (TTg hoặc Bộ trưởng)
    "Circular",           # Thông tư
    "JointCircular",      # Thông tư liên tịch
}

# Trạng thái hiệu lực tổng thể của văn bản (Document node).
DOCUMENT_LEGAL_STATUSES: set[str] = {
    "ACTIVE",             # Đang có hiệu lực
    "NOT_YET_EFFECTIVE",  # Đã ban hành nhưng chưa tới ngày hiệu lực
    "PARTIALLY_EFFECTIVE",# Một phần có hiệu lực, một phần bị bãi bỏ/sửa đổi
    "REPLACED",           # Đã được thay thế toàn bộ bởi văn bản khác
    "REPEALED",           # Đã bị bãi bỏ
    "EXPIRED",            # Hết thời hạn áp dụng
}

# Trạng thái hiệu lực ở cấp nội dung (Article/Clause/Point node).
CONTENT_LEGAL_STATUSES: set[str] = {
    "ACTIVE",    # Điều/Khoản/Điểm đang còn hiệu lực
    "AMENDED",   # Đã bị sửa đổi bởi văn bản khác (nội dung đã thay đổi)
    "REPEALED",  # Đã bị bãi bỏ
}

# Phân loại Phụ lục đính kèm văn bản.
APPENDIX_KINDS: set[str] = {
    "LEGAL_CONTENT",  # Phụ lục chứa nội dung quy phạm (điều khoản, bảng phân loại)
    "FORM",           # Mẫu đơn, mẫu biểu
    "LIST",           # Danh mục (danh mục ngành nghề, danh mục hàng hóa...)
    "TABLE",          # Bảng số liệu, bảng tỷ lệ, biểu phí
    "UNCLASSIFIED",   # Không xác định được loại
}

# Phân loại Văn bản đính kèm (ban hành kèm theo quyết định/nghị định).
ATTACHED_INSTRUMENT_KINDS: set[str] = {
    "REGULATION",  # Quy chế, Quy định
    "CHARTER",     # Điều lệ
    "STANDARD",    # Tiêu chuẩn, Quy chuẩn kỹ thuật
}

# Nhánh quyền lực ban hành văn bản (dùng để phân loại Issuer node).
ISSUER_BRANCHES: set[str] = {
    "LEGISLATIVE",  # Lập pháp: Quốc hội, UBTVQH
    "EXECUTIVE",    # Hành pháp: Chính phủ, TTg, Bộ, UBND
    "JUDICIAL",     # Tư pháp: TAND, VKSND, Hội đồng thẩm phán
    "OTHER",        # Cơ quan khác (NHNN, KTNN, tổ chức chính trị...)
}

# Phân loại kiểu trích dẫn trong quan hệ REFERS_TO.
CITATION_TYPES: set[str] = {
    "DIRECT",    # Trích dẫn trực tiếp số hiệu, số Điều cụ thể
    "INDIRECT",  # Trích dẫn gián tiếp ("theo quy định của pháp luật về...")
    "RANGE",     # Trích dẫn một dải Điều ("Điều 5 đến Điều 10")
}

# Phương pháp trích xuất quan hệ trích dẫn (REFERS_TO).
REFERENCE_EXTRACTION_METHODS: set[str] = {
    "RULE",            # Rule-based: regex nhận diện số hiệu văn bản/Điều
    "ENTITY_LINKING",  # Entity linking: khớp tên thực thể với registry
    "LLM",             # LLM extraction: mô hình ngôn ngữ trích xuất
}

# Phương pháp trích xuất quan hệ giữa văn bản (GUIDES, AMENDS...).
# Hiện tại chỉ hỗ trợ DIAGRAM (đồ thị quan hệ từ metadata VBPL).
DOCUMENT_RELATION_EXTRACTION_METHODS: set[str] = {
    "DIAGRAM",
}


# ── Relation rules ─────────────────────────────────────────────────────────────

# Whitelist cặp (head_type, tail_type) hợp lệ cho quan hệ GUIDES.
# Phản ánh thứ bậc ban hành: văn bản cấp cao hướng dẫn văn bản cấp thấp hơn.
# Ví dụ: Luật GUIDES Thông tư (Bộ ban hành Thông tư hướng dẫn Luật).
GUIDES_WHITELIST: set[tuple[str, str]] = {
    ("Constitution", "Law"),
    ("Constitution", "Ordinance"),
    ("Law", "Decree"),
    ("Law", "Decision"),
    ("Law", "Circular"),
    ("Ordinance", "Decree"),
    ("Resolution", "Decree"),
    ("Decree", "Circular"),
    ("Decree", "Decision"),
    ("Decree", "JointCircular"),
    ("Decision", "Circular"),
}

# Map tên quan hệ cũ (legacy) sang tên chuẩn hiện tại.
# Dùng khi đọc dữ liệu đã ghi với phiên bản ontology cũ hơn.
LEGACY_RELATION_ALIASES: dict[str, str] = {
    "AMENDED_BY":    "AMENDS",
    "REPEALED_BY":   "REPEALS",
    "REPLACED_BY":   "REPLACES",
    "IMPLEMENTED_BY":"GUIDES",
    "GUIDED_BY":     "GUIDES",
    "REFERENCES":    "REFERS_TO",
}

# Map tên loại thực thể do LLM tạo ra sang tên label chuẩn trong Neo4j.
# LLM hay dùng "Entity", "Concept", "Action" — cần map về label ontology.
ONTOLOGY_LABEL_MAP: dict[str, str] = {
    "Entity":  "LegalSubject",
    "Concept": "LegalConcept",
    "Action":  "LegalAction",
}


# ── Node labels ────────────────────────────────────────────────────────────────

# Tập label node được ghi vào Neo4j ở Phase 1 (pipeline hiện tại).
# Chỉ những label này mới được payload_builder tạo node — label khác bị reject.
PHASE1_PERSISTED_LABELS: set[str] = {
    "Document",           # Văn bản quy phạm
    "Issuer",             # Cơ quan ban hành
    "Appendix",           # Phụ lục
    "AttachedInstrument", # Văn bản ban hành kèm theo
    "Part",               # Phần (cấp cao nhất trong nội dung)
    "Chapter",            # Chương
    "Section",            # Mục
    "Subsection",         # Tiểu mục
    "Article",            # Điều (hoặc Synthetic Article nếu SOURCE_PRESERVED)
    "Clause",             # Khoản
    "Point",              # Điểm
    "LegalConcept",       # Khái niệm pháp lý được định nghĩa
    "LegalSubject",       # Chủ thể pháp lý (tổ chức, cá nhân, cơ quan)
    "LegalAction",        # Hành vi/hoạt động pháp lý
}

# Label chỉ tồn tại ở runtime (trong memory extraction), KHÔNG ghi vào Neo4j.
# Tương lai có thể thêm khi Phase 2 hỗ trợ.
RUNTIME_ONLY_LABELS: set[str] = {"Obligation", "Right", "Condition", "Exception"}

# Tất cả quan hệ hợp lệ trong ontology (Phase 1 + Phase 2).
RELATION_ENUM: set[str] = {
    "ISSUED_BY",     # Document → Issuer (ai ban hành)
    "CONTAINS",      # Cấu trúc phân cấp: Document→Chapter→Article→Clause→Point
    "AMENDS",        # Sửa đổi nội dung (có effective_from)
    "REPEALS",       # Bãi bỏ (có effective_from)
    "REPLACES",      # Thay thế toàn bộ văn bản
    "GUIDES",        # Hướng dẫn thi hành (phải nằm trong GUIDES_WHITELIST)
    "REFERS_TO",     # Trích dẫn, tham chiếu
    "DEFINES",       # Điều/Khoản định nghĩa LegalConcept
    "REGULATES",     # Điều/Khoản điều chỉnh LegalSubject/LegalAction
    "REQUIRES",      # LegalSubject yêu cầu điều kiện/LegalConcept
    "HAS_CONDITION", # Hành vi/nghĩa vụ có điều kiện áp dụng (Phase 2)
    "HAS_EXCEPTION", # Điều/Khoản có ngoại lệ (Phase 2)
}

# Tập con RELATION_ENUM được ghi vào Neo4j ở Phase 1.
# HAS_CONDITION và HAS_EXCEPTION để lại Phase 2.
PHASE1_RELATION_ENUM: set[str] = RELATION_ENUM - {"HAS_CONDITION", "HAS_EXCEPTION"}


# ── Relation constraints ───────────────────────────────────────────────────────

# Mỗi quan hệ khai báo:
#   valid_pairs / allowed_head+allowed_tail: cặp (head_label, tail_label) cho phép
#   no_self_loop: True nếu head_id == tail_id bị reject
#   required_properties: list field bắt buộc trên edge
#   property_types: kiểu dữ liệu kỳ vọng (dùng để validate khi write)
#   property_enums: giá trị enum cho field cụ thể
#   rule: tên rule đặc biệt (ví dụ "guides_whitelist")
CONSTRAINTS: dict[str, dict[str, Any]] = {
    # ── Cấu trúc ──────────────────────────────────────────────────────────────
    "ISSUED_BY": {
        # Chỉ Document được phép có quan hệ ISSUED_BY với Issuer.
        "valid_pairs": [("Document", "Issuer")],
        "no_self_loop": True,
    },
    "CONTAINS": {
        # Cây phân cấp văn bản: từ Document xuống đến Point.
        # Mọi cặp cha-con hợp lệ đều liệt kê tường minh ở đây.
        "valid_pairs": [
            ("Document", "Part"),
            ("Document", "Chapter"),
            ("Document", "Section"),
            ("Document", "Article"),        # Article trực thuộc Document (không có Chapter)
            ("Document", "Appendix"),
            ("Document", "AttachedInstrument"),
            ("AttachedInstrument", "Appendix"),
            ("AttachedInstrument", "Part"),
            ("AttachedInstrument", "Chapter"),
            ("AttachedInstrument", "Section"),
            ("AttachedInstrument", "Article"),
            ("Appendix", "Part"),
            ("Appendix", "Chapter"),
            ("Appendix", "Section"),
            ("Appendix", "Article"),
            ("Part", "Chapter"),
            ("Part", "Section"),
            ("Part", "Article"),
            ("Chapter", "Section"),
            ("Chapter", "Article"),
            ("Section", "Subsection"),
            ("Section", "Article"),
            ("Subsection", "Article"),
            ("Article", "Clause"),
            ("Clause", "Point"),
        ],
        "no_self_loop": True,
    },

    # ── Quan hệ thời gian (temporal) ──────────────────────────────────────────
    "AMENDS": {
        # Sửa đổi nội dung ở bất kỳ cấp nào (Document đến Point).
        # Bắt buộc có effective_from để tra cứu lịch sử.
        # source_ownership: HOST = trích từ chính văn bản này;
        #                   PROJECTED = suy ra từ văn bản khác.
        "valid_pairs": [
            (head, tail)
            for head in ("Document", "Article", "Clause", "Point")
            for tail in ("Document", "Article", "Clause", "Point")
        ],
        "no_self_loop": True,
        "required_properties": ["effective_from"],
        "property_types": {
            "source_ownership":              "string",
            "host_evidence_document_id":     "string",
            "host_evidence_source_unit_id":  "string",
            "host_evidence_char_start":      "integer",
            "host_evidence_char_end":        "integer",
            "projection_basis_candidate_id": "string",
        },
        "property_enums": {"source_ownership": {"HOST", "PROJECTED"}},
    },
    "REPEALS": {
        # Bãi bỏ hoàn toàn — cấu trúc tương tự AMENDS.
        "valid_pairs": [
            (head, tail)
            for head in ("Document", "Article", "Clause", "Point")
            for tail in ("Document", "Article", "Clause", "Point")
        ],
        "no_self_loop": True,
        "required_properties": ["effective_from"],
        "property_types": {
            "source_ownership":              "string",
            "host_evidence_document_id":     "string",
            "host_evidence_source_unit_id":  "string",
            "host_evidence_char_start":      "integer",
            "host_evidence_char_end":        "integer",
            "projection_basis_candidate_id": "string",
        },
        "property_enums": {"source_ownership": {"HOST", "PROJECTED"}},
    },
    "REPLACES": {
        # Thay thế toàn bộ một văn bản — chỉ ở cấp Document.
        "valid_pairs": [("Document", "Document")],
        "no_self_loop": True,
        "required_properties": ["effective_from"],
    },

    # ── Quan hệ hướng dẫn ─────────────────────────────────────────────────────
    "GUIDES": {
        # Văn bản cấp cao hướng dẫn văn bản cấp thấp.
        # validator sẽ kiểm tra cặp (head_type, tail_type) có trong GUIDES_WHITELIST.
        "valid_pairs": [("Document", "Document")],
        "rule": "guides_whitelist",
    },

    # ── Trích dẫn (citation) ──────────────────────────────────────────────────
    "REFERS_TO": {
        # Trích dẫn/tham chiếu giữa các đơn vị cấu trúc.
        # allowed_head/tail thay vì valid_pairs vì cần linh hoạt hơn.
        # required_properties_by_extraction_method: field bổ sung tùy phương pháp.
        "allowed_head": ["Appendix", "Article", "Clause", "Point"],
        "allowed_tail": [
            "Appendix",
            "Article",
            "Clause",
            "Point",
            "Document",
            "Part",
            "Chapter",
            "Section",
            "Subsection",
        ],
        "no_self_loop": False,  # Điều có thể tự trích dẫn chính mình (hiếm nhưng hợp lệ)
        "required_properties": [
            "citation_text",        # Đoạn văn bản gốc chứa trích dẫn
            "citation_type",        # DIRECT / INDIRECT / RANGE
            "extraction_method",    # RULE / ENTITY_LINKING / LLM
            "created_at",           # Timestamp tạo quan hệ
            "reference_bundle_id",  # UUID nhóm các trích dẫn cùng ngữ cảnh
            "reference_target_count",# Số đích được resolve từ cùng 1 citation
        ],
        "required_properties_by_extraction_method": {
            "RULE": [
                "resolver_name",      # Tên module resolver (vd "StructuralReferenceResolver")
                "resolver_version",
                "source_unit_id",     # canonical_id của đơn vị chứa trích dẫn
                "source_char_start",  # Vị trí ký tự bắt đầu trong source.txt
                "source_char_end",
            ],
            "ENTITY_LINKING": [
                "linker_name",
                "linker_version",
                "source_unit_id",
            ],
            "LLM": ["confidence", "llm_model", "checkpoint_id"],
        },
        "property_types": {
            "confidence":                    "float",
            "llm_model":                     "string",
            "created_at":                    "datetime",
            "citation_text":                 "string",
            "citation_type":                 "string",
            "extraction_method":             "string",
            "reference_bundle_id":           "string",
            "reference_target_count":        "integer",
            "resolver_name":                 "string",
            "resolver_version":              "string",
            "linker_name":                   "string",
            "linker_version":                "string",
            "source_unit_id":                "string",
            "source_char_start":             "integer",
            "source_char_end":               "integer",
            "checkpoint_id":                 "string",
            "source_ownership":              "string",
            "host_evidence_document_id":     "string",
            "host_evidence_source_unit_id":  "string",
            "host_evidence_char_start":      "integer",
            "host_evidence_char_end":        "integer",
            "projection_basis_candidate_id": "string",
        },
        "property_enums": {
            "citation_type":      CITATION_TYPES,
            "extraction_method":  REFERENCE_EXTRACTION_METHODS,
            "source_ownership":   {"HOST", "PROJECTED"},
        },
    },

    # ── Quan hệ ngữ nghĩa ─────────────────────────────────────────────────────
    "DEFINES": {
        # Điều/Khoản định nghĩa một khái niệm pháp lý.
        # Ví dụ: "Điều 4. Giải thích từ ngữ" DEFINES LegalConcept("doanh nghiệp").
        "allowed_head": ["Article", "Clause"],
        "allowed_tail": ["LegalConcept"],
        "required_properties": ["confidence", "llm_model", "created_at"],
    },
    "REGULATES": {
        # Điều/Khoản điều chỉnh hành vi hoặc chủ thể pháp lý.
        # Ví dụ: Điều 5 REGULATES LegalSubject("doanh nghiệp nhà nước").
        "allowed_head": ["Article", "Clause"],
        "allowed_tail": ["LegalSubject", "LegalAction"],
        "required_properties": ["confidence", "llm_model", "created_at"],
    },
    "REQUIRES": {
        # Chủ thể pháp lý cần có điều kiện/tư cách/giấy phép gì.
        # Ví dụ: LegalSubject("công ty") REQUIRES LegalConcept("vốn pháp định").
        # Phase 1: chỉ LegalSubject → LegalConcept.
        "allowed_head": ["LegalSubject"],
        "allowed_tail": ["LegalConcept"],
        "no_self_loop": True,
        "required_properties": ["confidence", "llm_model", "created_at"],
    },

    # ── Phase 2 (chưa ghi Neo4j) ─────────────────────────────────────────────
    "HAS_CONDITION": {
        # Hành vi/nghĩa vụ pháp lý có điều kiện áp dụng.
        "allowed_head": ["LegalAction", "Obligation", "Right"],
        "allowed_tail": ["Condition"],
        "no_self_loop": True,
        "required_properties": ["confidence", "llm_model", "created_at"],
    },
    "HAS_EXCEPTION": {
        # Điều/Khoản có ngoại lệ không áp dụng.
        "allowed_head": ["Article", "Clause", "LegalAction"],
        "allowed_tail": ["Exception"],
        "no_self_loop": True,
        "required_properties": ["confidence", "llm_model", "created_at"],
    },
}


# ── Node field contracts ───────────────────────────────────────────────────────

# Field bắt buộc của mỗi loại node (thiếu → PayloadBuildError).
# Thực thi ở application layer vì Neo4j Community không hỗ trợ NOT NULL constraint.
NODE_REQUIRED_FIELDS: dict[str, list[str]] = {
    "Document": [
        "id",           # Canonical ID (vd: "luat_doanh_nghiep_2020")
        "doc_type",     # Giá trị trong DOCUMENT_TYPES
        "number",       # Số hiệu văn bản (vd: "59/2020/QH14")
        "legal_status", # Giá trị trong DOCUMENT_LEGAL_STATUSES
        "effective_from",
        "issuer_name",  # Tên cơ quan ban hành (denormalized để query nhanh)
    ],
    "Issuer": [
        "id",   # Slug tên cơ quan (vd: "quoc_hoi")
        "name", # Tên đầy đủ
    ],
    "Appendix": [
        "id",
        "scope",          # ID Document cha
        "heading",        # Tiêu đề phụ lục
        "content_raw",    # Nội dung thô (hoặc tổng hợp từ Articles con)
        "appendix_kind",  # Giá trị trong APPENDIX_KINDS
        "effective_from",
        "legal_status",
    ],
    "AttachedInstrument": [
        "id",
        "scope",           # ID Document cha
        "heading",         # Tiêu đề văn bản đính kèm
        "adoption_text",   # Câu "Ban hành kèm theo Quyết định số..."
        "content_raw",
        "instrument_kind", # Giá trị trong ATTACHED_INSTRUMENT_KINDS
    ],
    "Part":       ["id", "number", "title"],
    "Chapter":    ["id", "number", "title"],
    "Section":    ["id", "number", "title"],
    "Subsection": ["id", "number", "title"],
    "Article": [
        "id",
        "number",       # Số Điều (hoặc 'SP_N' nếu synthetic)
        "content_raw",
        "effective_from",
        "legal_status",
    ],
    "Clause": ["id", "number", "content_raw", "effective_from", "legal_status"],
    "Point":  ["id", "label", "content_raw"],
    "LegalConcept": ["id", "name"],
    "LegalSubject": ["id", "name"],
    "LegalAction":  ["id", "name"],
}

# Enum constraint trên field của node (thiếu hoặc sai giá trị → validation error).
NODE_ENUMS: dict[str, dict[str, set[str]]] = {
    "Document": {
        "doc_type":     DOCUMENT_TYPES,
        "legal_status": DOCUMENT_LEGAL_STATUSES,
    },
    "Appendix": {
        "appendix_kind": APPENDIX_KINDS,
        "legal_status":  CONTENT_LEGAL_STATUSES,
    },
    "AttachedInstrument": {
        "instrument_kind": ATTACHED_INSTRUMENT_KINDS,
    },
    "Article": {
        "legal_status": CONTENT_LEGAL_STATUSES,
    },
    "Clause": {
        "legal_status": CONTENT_LEGAL_STATUSES,
    },
    "Point": {
        # Point không có legal_status required; nếu có phải thuộc tập này.
        "legal_status": CONTENT_LEGAL_STATUSES,
    },
}

# Field metadata tùy chọn cho mỗi loại node.
# Có thể vắng mặt khi ghi — không raise error nếu thiếu.
NODE_OPTIONAL_FIELDS: dict[str, list[str]] = {
    "Document": [
        "title",        # Tên đầy đủ văn bản
        "issued_date",  # Ngày ký ban hành (có thể khác effective_from)
        "effective_to", # Ngày hết hiệu lực (None nếu chưa xác định)
        "expiry_date",  # Ngày hết hạn áp dụng (dành cho văn bản tạm thời)
        "sector",       # Lĩnh vực (vd: "Tài chính", "Lao động")
        "field",        # Ngành (chi tiết hơn sector)
        "signer_title", # Chức danh người ký (vd: "Bộ trưởng")
        "signer_name",  # Tên người ký
        "source_url",   # URL nguồn crawl
        "updated_at",   # Timestamp cập nhật cuối
    ],
    "Appendix": [
        "number",     # Số thứ tự phụ lục (vd: "I", "1")
        "title",
        "effective_to",
        "embedding",  # Vector embedding nội dung (Phase 3)
        "updated_at",
    ],
    "AttachedInstrument": [
        "title",
        "updated_at",
    ],
    "Article": [
        "title",        # Tiêu đề Điều (vd: "Điều 4. Giải thích từ ngữ")
        "effective_to",
        "embedding",    # Vector embedding nội dung Điều (Phase 3)
        "updated_at",
        # True nếu Article là synthetic chunk (tạo từ SOURCE_PRESERVED document).
        # Số hiệu bắt đầu bằng SYNTHETIC_ARTICLE_NUMBER_PREFIX ('SP_').
        # Xem: orchestrator._synthetic_articles_from_unparsed
        "is_synthetic",
    ],
    "Clause": [
        "effective_to",
        "embedding",
        "updated_at",
    ],
    "Point": [
        # Point thường kế thừa legal_status từ Clause cha, nhưng có thể ghi riêng.
        "effective_from",
        "effective_to",
        "legal_status",
        "updated_at",
    ],
    "LegalConcept": [
        "aliases",     # Các tên gọi khác (list string)
        "description", # Giải thích ngắn
    ],
    "LegalSubject": [
        "aliases",
        "description",
    ],
    "LegalAction": [
        "aliases",
        "description",
    ],
}
