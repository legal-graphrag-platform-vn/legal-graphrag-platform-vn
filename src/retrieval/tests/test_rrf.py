from src.retrieval.fusion.reciprocal_rank_fusion import ReciprocalRankFusion
from src.retrieval.models import RetrievedUnit


def test_rrf_fusion_ordering():
    """
    Test tính điểm và sắp xếp của RRF khi trộn 2 list kết quả.
    """
    fusion = ReciprocalRankFusion(k=60)
    
    # Giả lập Vector results (Rank 1: A, Rank 2: B, Rank 3: C)
    vector_results = [
        RetrievedUnit(id="A", label="Article", content_raw="A", document_id="d", citation_label="A", vector_score=0.9),
        RetrievedUnit(id="B", label="Article", content_raw="B", document_id="d", citation_label="B", vector_score=0.8),
        RetrievedUnit(id="C", label="Article", content_raw="C", document_id="d", citation_label="C", vector_score=0.7),
    ]
    
    # Giả lập BM25 results (Rank 1: B, Rank 2: A, Rank 3: D)
    bm25_results = [
        RetrievedUnit(id="B", label="Article", content_raw="B", document_id="d", citation_label="B", bm25_score=10.5),
        RetrievedUnit(id="A", label="Article", content_raw="A", document_id="d", citation_label="A", bm25_score=9.0),
        RetrievedUnit(id="D", label="Article", content_raw="D", document_id="d", citation_label="D", bm25_score=5.0),
    ]
    
    # Kì vọng: 
    # B: Rank 2 (Vector) + Rank 1 (BM25) => 1/62 + 1/61 = 0.016129 + 0.016393 = 0.032522
    # A: Rank 1 (Vector) + Rank 2 (BM25) => 1/61 + 1/62 = 0.016393 + 0.016129 = 0.032522
    # Hai thằng B và A có tổng rank như nhau -> Thứ tự có thể A trước B hoặc B trước A tùy implementation python
    # C: Rank 3 (Vector) => 1/63 = 0.015873
    # D: Rank 3 (BM25) => 1/63 = 0.015873
    
    # Tuy nhiên, nếu chỉnh sửa Vector results: B rank 1, A rank 2
    # và BM25: B rank 1, A rank 2 => B chắc chắn phải top 1.
    
    vector_results[0], vector_results[1] = vector_results[1], vector_results[0] # Đổi A và B -> Vector: B, A, C
    
    fused = fusion.fuse(vector_results, bm25_results, top_n=5)
    
    assert len(fused) == 4
    
    # Top 1 chắc chắn là B vì đứng Rank 1 ở cả hai list
    assert fused[0].id == "B"
    
    # Top 2 chắc chắn là A vì đứng Rank 2 ở cả hai list
    assert fused[1].id == "A"
    
    # Kiểm tra việc giữ lại metadata score
    assert fused[0].vector_score == 0.8 # Do ta gán cứng ở trên
    assert fused[0].bm25_score == 10.5
