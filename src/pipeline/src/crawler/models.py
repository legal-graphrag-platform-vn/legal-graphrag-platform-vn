"""Pydantic model cho output của Crawler — khớp metadata.json spec trong
plans/04_graph_construction_pipeline.md Step 0.

`doc_id`/`doc_type` đặt tên khác `id`/`type` trong spec gốc để tránh đụng
built-in `id`/`type`; field alias giữ JSON output đúng tên spec khi serialize.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """Metadata "sự thật tuyệt đối" cào trực tiếp từ trang web (không để LLM đoán)."""

    doc_id: str = Field(alias="doc_id", description="Document ID convention, vd 'LDN2020'")
    title: str
    number: str = Field(description="Số hiệu văn bản, vd '59/2020/QH14'")
    doc_type: str = Field(description="Law|Decree|Circular|Resolution|Decision")
    issued_by: str | None = None
    issued_date: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    status: str = Field(default="active")
    source_url: str

    model_config = {"populate_by_name": True}
