from datetime import date

from src.retrieval.context.temporal_filter import TemporalFilter
from src.retrieval.models import RetrievedUnit, TemporalQuery


def test_temporal_filter_no_temporal():
    """
    Trường hợp truy vấn không có mốc thời gian -> giải quyết conflict và trả về bản mới nhất.
    """
    filter_obj = TemporalFilter()
    temporal = TemporalQuery(has_temporal=False)

    units = [
        RetrievedUnit(
            id="1", label="Article", content_raw="Bản cũ", document_id="doc1", 
            document_number="L102", article_number="Điều 1", citation_label="Điều 1, L102",
            effective_from=date(2010, 1, 1), effective_to=date(2020, 12, 31)
        ),
        RetrievedUnit(
            id="2", label="Article", content_raw="Bản mới", document_id="doc2", 
            document_number="L102", article_number="Điều 1", citation_label="Điều 1, L102",
            effective_from=date(2021, 1, 1), effective_to=None
        ),
    ]

    resolved = filter_obj.filter_and_resolve(units, temporal)
    
    assert len(resolved) == 1
    assert resolved[0].id == "2" # Phải ưu tiên bản mới nhất


def test_temporal_filter_with_target_date():
    """
    Trường hợp truy vấn có mốc thời gian -> lọc các bản thoả mãn thời gian đó.
    """
    filter_obj = TemporalFilter()
    temporal = TemporalQuery(
        has_temporal=True, 
        resolved_from=date(2015, 6, 1) # Hỏi về năm 2015
    )

    units = [
        RetrievedUnit(
            id="1", label="Article", content_raw="Bản cũ", document_id="doc1", 
            document_number="L102", article_number="Điều 1", citation_label="Điều 1, L102",
            effective_from=date(2010, 1, 1), effective_to=date(2020, 12, 31)
        ),
        RetrievedUnit(
            id="2", label="Article", content_raw="Bản mới", document_id="doc2", 
            document_number="L102", article_number="Điều 1", citation_label="Điều 1, L102",
            effective_from=date(2021, 1, 1), effective_to=None
        ),
    ]

    resolved = filter_obj.filter_and_resolve(units, temporal)
    
    assert len(resolved) == 1
    assert resolved[0].id == "1" # Năm 2015 thì bản cũ còn hiệu lực, bản mới chưa có hiệu lực


def test_temporal_filter_conflict_resolution():
    """
    Nếu tại 1 thời điểm (do dữ liệu lỗi hoặc do quy định chồng chéo), có nhiều bản còn hiệu lực.
    Ta phải giải quyết conflict bằng cách lấy bản có effective_from gần nhất (mới nhất).
    """
    filter_obj = TemporalFilter()
    temporal = TemporalQuery(has_temporal=True, resolved_from=date(2022, 1, 1))

    units = [
        # Cả 2 bản đều chưa hết hiệu lực hoặc lỗi data (không có effective_to)
        RetrievedUnit(
            id="1", label="Article", content_raw="Bản gốc", document_id="doc1", 
            document_number="L102", article_number="Điều 1", citation_label="Điều 1, L102",
            effective_from=date(2010, 1, 1), effective_to=None
        ),
        RetrievedUnit(
            id="2", label="Article", content_raw="Bản sửa đổi", document_id="doc2", 
            document_number="L102", article_number="Điều 1", citation_label="Điều 1, L102",
            effective_from=date(2021, 1, 1), effective_to=None
        ),
    ]

    resolved = filter_obj.filter_and_resolve(units, temporal)
    
    # Cả 2 đều qua bước filter vì effective_from <= 2022 và effective_to is None
    # Nhưng ở bước _resolve_conflicts, bản "Bản sửa đổi" (2021) sẽ ghi đè bản 2010
    assert len(resolved) == 1
    assert resolved[0].id == "2"
