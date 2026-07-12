import re
from datetime import date, datetime
from typing import Optional, Tuple
import json

from src.infrastructure.llm.base import LLMClient
from src.retrieval.models import TemporalQuery


class TemporalParser:
    """
    Trích xuất mốc thời gian từ truy vấn (Rule-based + LLM fallback).
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client
        # Regex cho dạng "năm YYYY"
        self.year_pattern = re.compile(r"(?:năm|trong năm)\s*(\d{4})", re.IGNORECASE)
        # Regex cho "ngày DD tháng MM năm YYYY"
        self.date_pattern = re.compile(r"ngày\s*(\d{1,2})\s*tháng\s*(\d{1,2})\s*năm\s*(\d{4})", re.IGNORECASE)

    def parse(self, query: str) -> TemporalQuery:
        """
        Phân tích truy vấn và trả về TemporalQuery.
        Ưu tiên rule-based, nếu không thấy và query có vẻ phức tạp -> gọi LLM.
        """
        
        has_temporal = False
        expression = None
        resolved_from = None
        resolved_to = None
        granularity = None

        # 1. Rule-based: Thử match ngày cụ thể
        date_match = self.date_pattern.search(query)
        if date_match:
            day, month, year = date_match.groups()
            try:
                dt = date(int(year), int(month), int(day))
                has_temporal = True
                expression = date_match.group(0)
                resolved_from = dt
                resolved_to = dt
                granularity = "day"
                return TemporalQuery(
                    has_temporal=has_temporal,
                    expression=expression,
                    resolved_from=resolved_from,
                    resolved_to=resolved_to,
                    granularity=granularity
                )
            except ValueError:
                pass # Invalid date, fallback
                
        # 2. Rule-based: Thử match năm
        year_match = self.year_pattern.search(query)
        if year_match:
            year = int(year_match.group(1))
            has_temporal = True
            expression = year_match.group(0)
            resolved_from = date(year, 1, 1)
            resolved_to = date(year, 12, 31)
            granularity = "year"
            return TemporalQuery(
                has_temporal=has_temporal,
                expression=expression,
                resolved_from=resolved_from,
                resolved_to=resolved_to,
                granularity=granularity
            )

        # 3. LLM Fallback: Nâng cao (ví dụ: "trước khi Luật X có hiệu lực")
        if self.llm_client and any(kw in query.lower() for kw in ["trước", "sau", "hiệu lực", "thời điểm", "áp dụng"]):
            system_prompt = (
                "Extract temporal conditions from the legal query. "
                "Respond in JSON format: {\"has_temporal\": bool, \"expression\": \"str or null\", "
                "\"resolved_from\": \"YYYY-MM-DD or null\", \"resolved_to\": \"YYYY-MM-DD or null\", \"granularity\": \"day/month/year or null\"}"
            )
            try:
                response = self.llm_client.generate_text(
                    system_prompt=system_prompt,
                    user_prompt=query,
                    temperature=0.0,
                    response_format="json_object"
                )
                data = json.loads(response)
                
                def parse_date(d_str: str) -> Optional[date]:
                    if not d_str:
                        return None
                    try:
                        return datetime.strptime(d_str, "%Y-%m-%d").date()
                    except ValueError:
                        return None
                        
                return TemporalQuery(
                    has_temporal=data.get("has_temporal", False),
                    expression=data.get("expression"),
                    resolved_from=parse_date(data.get("resolved_from")),
                    resolved_to=parse_date(data.get("resolved_to")),
                    granularity=data.get("granularity")
                )
            except Exception:
                pass # Ignore LLM errors and fallback to No temporal
                
        return TemporalQuery(has_temporal=False)
