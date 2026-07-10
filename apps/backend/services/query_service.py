import uuid
from typing import Tuple, List, Dict

class RAGService:
    @staticmethod
    def retrieve(query: str) -> Tuple[str, List[Dict]]:
        """
        Tìm kiếm tài liệu liên quan dựa trên câu hỏi của người dùng.
        Hiện tại đang giả lập (Mock) các dữ liệu luật để phục vụ việc demo UI và SSE.
        Trong thực tế, hàm này sẽ kết nối với Vector DB hoặc GraphRAG.
        """
        query_lower = query.lower()
        sources = []
        context_parts = []

        # 1.   Xử lý tìm kiếm trích lục cho Luật Doanh nghiệp (thành lập công ty cổ phần)
        if "công ty cổ phần" in query_lower or "luật doanh nghiệp" in query_lower:
            sources.append({
                "id": str(uuid.uuid4()),
                "title": "Luật Doanh nghiệp 2020 - Điều 111",
                "content": "Công ty cổ phần là doanh nghiệp trong đó: Vốn điều lệ được chia thành các phần bằng nhau gọi là cổ phần; Cổ đông có thể là tổ chức, cá nhân; số lượng cổ đông tối thiểu là 03 và không hạn chế số lượng tối đa. Cổ đông chỉ chịu trách nhiệm về các khoản nợ và nghĩa vụ tài sản khác của doanh nghiệp trong phạm vi số vốn đã góp vào doanh nghiệp.",
                "page": "45",
                "score": 0.95,
                "url": "https://data.vietnam.gov.vn/document/luat-doanh-nghiep-2020"
            })
            sources.append({
                "id": str(uuid.uuid4()),
                "title": "Nghị định 01/2021/NĐ-CP - Đăng ký doanh nghiệp",
                "content": "Hồ sơ đăng ký doanh nghiệp đối với công ty cổ phần bao gồm: Giấy đề nghị đăng ký doanh nghiệp; Điều lệ công ty; Danh sách cổ đông sáng lập; Bản sao giấy tờ pháp lý của cá nhân đối với cổ đông sáng lập...",
                "page": "12",
                "score": 0.89,
                "url": "https://data.vietnam.gov.vn/document/nghi-dinh-01-2021-nd-cp"
            })
            
        # 2.   Xử lý tìm kiếm trích lục cho Thỏa thuận bảo mật (NDA)
        elif "nda" in query_lower or "bảo mật" in query_lower:
            sources.append({
                "id": str(uuid.uuid4()),
                "title": "Bộ luật Dân sự 2015 - Điều 387: Thông tin trong giao kết hợp đồng",
                "content": "Trường hợp một bên có thông tin bảo mật thu được từ việc giao kết hợp đồng thì phải bảo mật thông tin đó và không được sử dụng thông tin đó vào mục đích riêng hoặc mục đích bất hợp pháp khác của mình. Bên vi phạm mà gây thiệt hại thì phải bồi thường.",
                "page": "112",
                "score": 0.92,
                "url": "https://data.vietnam.gov.vn/document/bo-luat-dan-su-2015"
            })
            sources.append({
                "id": str(uuid.uuid4()),
                "title": "Cẩm nang Soạn thảo Hợp đồng Thương mại",
                "content": "Thỏa thuận bảo mật thông tin (NDA) cần quy định rõ: Định nghĩa thông tin bảo mật; Nghĩa vụ của bên nhận thông tin; Thời hạn bảo mật (thường từ 2-5 năm sau khi chấm dứt hợp đồng); Các trường hợp ngoại lệ không cần bảo mật; Biện pháp xử lý khi vi phạm.",
                "page": "78",
                "score": 0.85
            })

        # 3.   Xử lý tìm kiếm trích lục cho Thuế thu nhập cá nhân (TNCN)
        elif "thuế" in query_lower or "tncn" in query_lower or "giảm trừ" in query_lower:
            sources.append({
                "id": str(uuid.uuid4()),
                "title": "Nghị quyết 954/2020/UBTVQH14 - Điều chỉnh mức giảm trừ gia cảnh thuế TNCN",
                "content": "Điều chỉnh mức giảm trừ gia cảnh quy định tại Luật Thuế thu nhập cá nhân như sau: Mức giảm trừ đối với đối tượng nộp thuế là 11 triệu đồng/tháng (132 triệu đồng/năm); Mức giảm trừ đối với mỗi người phụ thuộc là 4,4 triệu đồng/tháng.",
                "page": "2",
                "score": 0.97,
                "url": "https://data.vietnam.gov.vn/document/nghi-quyet-954-2020-ubtvqh14"
            })

        # 4.   Xử lý tìm kiếm trích lục cho Sở hữu trí tuệ (Nhãn hiệu)
        elif "nhãn hiệu" in query_lower or "sở hữu trí tuệ" in query_lower:
            sources.append({
                "id": str(uuid.uuid4()),
                "title": "Luật Sở hữu trí tuệ 2005 (sửa đổi 2022) - Điều 72",
                "content": "Nhãn hiệu được bảo hộ nếu đáp ứng các điều kiện sau đây: Là dấu hiệu nhìn thấy được dưới dạng chữ cái, từ ngữ, hình vẽ, hình ảnh, hình ba chiều hoặc sự kết hợp các yếu tố đó, được thể hiện bằng một hoặc nhiều màu sắc hoặc dấu hiệu âm thanh thể hiện được dưới dạng đồ họa; Có khả năng phân biệt hàng hóa, dịch vụ của chủ sở hữu nhãn hiệu với hàng hóa, dịch vụ của chủ thể khác.",
                "page": "34",
                "score": 0.94,
                "url": "https://data.vietnam.gov.vn/document/luat-so-huu-tri-tue-2022"
            })

        # 5.   Trường hợp câu hỏi chung chung không khớp từ khóa
        else:
            sources.append({
                "id": str(uuid.uuid4()),
                "title": "Hướng dẫn sử dụng Hệ thống Trợ lý RAG",
                "content": "Hệ thống đang chạy chế độ Tri thức nền tảng pháp luật. Bạn có thể đặt các câu hỏi liên quan đến Luật Doanh nghiệp, Luật Dân sự, Luật Thuế TNCN hoặc Sở hữu trí tuệ để nhận được trích dẫn tài liệu chính xác nhất.",
                "page": "1",
                "score": 0.70
            })

        # 6.   Gộp toàn bộ nội dung tài liệu tìm kiếm được thành một chuỗi Context duy nhất
        for src in sources:
            context_parts.append(f"[{src['title']}]: {src['content']}")
            
        context_text = "\n\n".join(context_parts)
        
        # 7.   Trả về bộ đôi (context_text, sources)
        return context_text, sources
