"""Output sinks cho Decision Gate (Step 5) — accepted/review/rejected JSONL.

Phạm vi M1+M2: dừng ở đây. KHÔNG ghi Neo4j (Neo4j Writer là Milestone 3, ngoài
phạm vi nhiệm vụ hiện tại) — `AcceptedLog` chỉ ghi file JSONL làm input sẵn sàng
cho Neo4j Writer sau này.
"""

from __future__ import annotations

import json
from pathlib import Path


class JsonlSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


class AcceptedLog(JsonlSink):
    """confidence >= ngưỡng auto (0.7 mặc định)."""


class ReviewQueue(JsonlSink):
    """ngưỡng review <= confidence < ngưỡng auto (0.3-0.7 mặc định)."""


class RejectionLog(JsonlSink):
    """confidence < ngưỡng review (0.3 mặc định)."""
