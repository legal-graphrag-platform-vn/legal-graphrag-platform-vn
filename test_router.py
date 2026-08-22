import sys
from datetime import date

sys.path.append('.')

from src.retrieval.config import RetrievalConfig
from src.retrieval.routing.router import IntentRouter
from src.retrieval.models import RetrievalRequest
from src.retrieval.ports import Clock

class DummyClock(Clock):
    def today(self) -> date:
        return date(2023, 10, 1)

def main():
    config = RetrievalConfig()
    router = IntentRouter(config=config, clock=DummyClock())

    questions = [
        "Điều kiện thành lập công ty TNHH là gì?",
        "Thế nào là doanh nghiệp nhà nước?",
        "Văn bản nào hướng dẫn thi hành Luật Doanh nghiệp?",
        "Luật Doanh nghiệp 2020 còn hiệu lực không?",
        "So sánh điểm giống và khác nhau trước và sau khi sửa đổi",
        "Thủ tục đăng ký kinh doanh phải qua nhiều bước như thế nào?",
    ]

    for q in questions:
        req = RetrievalRequest(query=q)
        try:
            res = router.route(req)
            print(f"Câu hỏi: {q}")
            print(f" -> Intent (Phân loại): {res.decision.intent.value}")
            print(f" -> Strategy (Chiến thuật): {res.decision.strategy.value}")
            print(f" -> Reason (Lý do chọn): {res.decision.decision_reason}")
        except Exception as e:
            print(f"Câu hỏi: {q}")
            print(f" -> Lỗi: {e}")
        print("-" * 70)

if __name__ == "__main__":
    main()
