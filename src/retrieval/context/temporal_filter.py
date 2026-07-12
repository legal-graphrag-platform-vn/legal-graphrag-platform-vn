from collections import defaultdict
from typing import List

from src.retrieval.models import RetrievedUnit, TemporalQuery


class TemporalFilter:
    """
    Bộ lọc Temporal deterministics.
    """

    def filter_and_resolve(self, units: List[RetrievedUnit], temporal: TemporalQuery) -> List[RetrievedUnit]:
        """
        Lọc danh sách các legal units theo thời gian truy vấn (nếu có).
        Giải quyết conflict: Nếu có nhiều bản của cùng 1 điều luật thoả mãn, lấy bản mới nhất.
        """
        
        if not temporal.has_temporal or not temporal.resolved_from:
            # Nếu query không có thông tin thời gian, có thể lấy mặc định bản mới nhất (hiện hành)
            # Nhưng ở Phase 2 ta giả định trả về nguyên bản để Reranker quyết định, 
            # hoặc ta có thể filter lấy bản mới nhất của mỗi Article.
            return self._resolve_conflicts(units)
            
        target_date = temporal.resolved_from
        valid_units = []
        
        for unit in units:
            # Nếu unit không có ngày hiệu lực thì mặc định cho qua
            if not unit.effective_from:
                valid_units.append(unit)
                continue
                
            # Kiểm tra hiệu lực
            is_effective = unit.effective_from <= target_date
            is_not_expired = unit.effective_to is None or unit.effective_to > target_date
            
            if is_effective and is_not_expired:
                valid_units.append(unit)
                
        # Gỡ xung đột sau khi lọc
        return self._resolve_conflicts(valid_units)
        
    def _resolve_conflicts(self, units: List[RetrievedUnit]) -> List[RetrievedUnit]:
        """
        Nếu có nhiều unit có cùng document_number và article_number, 
        lấy bản có effective_from mới nhất (hiệu lực sau cùng).
        """
        # Nhóm theo (document_number, article_number, clause_number)
        groups = defaultdict(list)
        for unit in units:
            # Khóa nhóm, ví dụ: ('Luật Doanh nghiệp 2020', 'Điều 46', 'Khoản 1')
            key = (unit.document_number, unit.article_number, unit.clause_number)
            groups[key].append(unit)
            
        resolved = []
        for key, group in groups.items():
            if len(group) == 1:
                resolved.append(group[0])
            else:
                # Xếp giảm dần theo effective_from (bản mới nhất ở đầu)
                # Nếu không có effective_from, cho xuống cuối
                sorted_group = sorted(
                    group, 
                    key=lambda x: x.effective_from.toordinal() if x.effective_from else 0, 
                    reverse=True
                )
                resolved.append(sorted_group[0])
                
        return resolved
