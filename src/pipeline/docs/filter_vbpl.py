"""
Lọc và phân loại văn bản pháp luật từ 7 file lược đồ vbpl.vn
Output: lX_filtered.md cho mỗi file, nhóm theo ✅ / ⚠️ / ❌
"""

import re
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Metadata từng luật
LAW_META = {
    "l1": {
        "title": "Luật Sửa đổi, bổ sung một số điều của Luật Doanh nghiệp số 76/2025/QH15",
        "hieu_luc": "Còn hiệu lực",
        "section": "Văn bản áp dụng",  # l1 không có "quy định chi tiết"
        "strict": True,  # lọc chặt hơn vì lấy từ "áp dụng"
    },
    "l2": {
        "title": "Luật Doanh nghiệp số 59/2020/QH14 (Văn bản hợp nhất)",
        "hieu_luc": "Còn hiệu lực",
        "section": "Văn bản quy định chi tiết, hướng dẫn thi hành",
        "strict": False,
    },
    "l3": {
        "title": "Luật Doanh nghiệp số 59/2020/QH14",
        "hieu_luc": "Còn hiệu lực",
        "section": "Văn bản quy định chi tiết, hướng dẫn thi hành",
        "strict": False,
    },
    "l4": {
        "title": "Luật Doanh nghiệp số 68/2014/QH13",
        "hieu_luc": "Hết hiệu lực (thay thế bởi Luật 59/2020/QH14)",
        "section": "Văn bản quy định chi tiết, hướng dẫn thi hành",
        "strict": False,
    },
    "l5": {
        "title": "Luật Sửa đổi, bổ sung Điều 170 của Luật Doanh nghiệp số 37/2013/QH13",
        "hieu_luc": "Hết hiệu lực",
        "section": "Văn bản quy định chi tiết, hướng dẫn thi hành",
        "strict": False,
    },
    "l6": {
        "title": "Luật Doanh nghiệp số 60/2005/QH11",
        "hieu_luc": "Hết hiệu lực (thay thế bởi Luật 68/2014/QH13)",
        "section": "Văn bản quy định chi tiết, hướng dẫn thi hành",
        "strict": False,
    },
    "l7": {
        "title": "Luật Doanh nghiệp số 13/1999/QH10",
        "hieu_luc": "Hết hiệu lực (thay thế bởi Luật 60/2005/QH11)",
        "section": "Văn bản quy định chi tiết, hướng dẫn thi hành",
        "strict": False,
    },
}

# ── Từ khóa phân loại ─────────────────────────────────────────────────────────

KEEP_KEYWORDS = [
    "đăng ký doanh nghiệp",
    "đăng ký kinh doanh",
    "quản lý doanh nghiệp",
    "quản lý nhà nước.*doanh nghiệp",
    "sau đăng ký thành lập",
    "quản trị công ty",
    "vốn nhà nước tại doanh nghiệp",
    "vốn nhà nước vào doanh nghiệp",
    "đầu tư vốn nhà nước",
    "cổ phần hóa",
    "chuyển doanh nghiệp.*thành công ty cổ phần",
    "chuyển đổi.*công ty trách nhiệm hữu hạn",
    "doanh nghiệp nhà nước",
    "người đại diện phần vốn nhà nước",
    "chức danh.*chức vụ.*doanh nghiệp",
    "kiểm soát viên.*doanh nghiệp",
    "công bố thông tin.*doanh nghiệp",
    "giám sát.*doanh nghiệp",
    "đánh giá hiệu quả.*doanh nghiệp",
    "xử phạt vi phạm.*kế hoạch và đầu tư",
    "quy định chi tiết.*luật doanh nghiệp",
    "hướng dẫn.*luật doanh nghiệp",
    "phá sản doanh nghiệp",
    "giải thể doanh nghiệp",
    "tổ chức lại doanh nghiệp",
    "bán.*giao.*doanh nghiệp",
    "sắp xếp.*doanh nghiệp",
    r"công ty\s+(tnhh|trách nhiệm hữu hạn|cổ phần|hợp danh)",
    "hộ kinh doanh",
    "tiền lương.*doanh nghiệp",
    "thù lao.*doanh nghiệp nhà nước",
    "quỹ phát triển doanh nghiệp",
    "doanh nghiệp nhỏ và vừa",
    "doanh nghiệp khoa học và công nghệ",
    "doanh nghiệp quốc phòng",
    "tái cơ cấu doanh nghiệp",
    "cơ cấu lại.*doanh nghiệp",
    "trái phiếu doanh nghiệp",
    "phát hành.*cổ phần",
    "đặt tên doanh nghiệp",
    "mã số doanh nghiệp",
    "hệ thống thông tin.*đăng ký doanh nghiệp",
    "phòng đăng ký kinh doanh",
]

PARTIAL_KEYWORDS = [
    "chứng khoán",
    "thị trường chứng khoán",
    "công ty đại chúng",
    "niêm yết",
    "công ty chứng khoán",
    "công ty quản lý quỹ",
    "quỹ đầu tư",
    "đầu tư mạo hiểm",
    "tổ chức tài chính vi mô",
    "tổ chức tín dụng phi ngân hàng",
    "điều lệ.*tập đoàn",
    "điều lệ.*tổng công ty",
    "điều kiện kinh doanh",
    "ngành nghề.*điều kiện",
    "đầu tư nước ngoài.*doanh nghiệp",
    "sở giao dịch hàng hóa",
    "quỹ bảo lãnh tín dụng",
    "phục hồi.*phá sản",
]

REJECT_KEYWORDS = [
    r"TT-NHNN",
    r"QĐ-NHNN",
    r"tổ chức tín dụng\b(?!.*phi ngân hàng)",
    "ngân hàng thương mại",
    "nợ xấu",
    "chi nhánh ngân hàng",
    "UBND",
    "Ủy ban nhân dân",
    "HĐND",
    "Hội đồng nhân dân",
    r"TT-BNNPTNT",
    "nông nghiệp và phát triển nông thôn",
    "chăn nuôi",
    "thủy sản",
    "trồng trọt",
    "bảo vệ thực vật",
    "thú y",
    "lâm nghiệp",
    "thủy lợi",
    "vận tải.*biển",
    "hàng hải",
    "hoa tiêu",
    r"TT-BYT",
    "y tế.*hành nghề",
    "hành nghề y",
    "dược phẩm",
    "y học cổ truyền",
    r"TT-BGTVT",
    "giao thông vận tải",
    r"TT-BXD",
    "xây dựng.*điều kiện",
    "nhà chung cư",
    "Hiến pháp",
    "Bộ luật Tố tụng",
    "Luật Tố cáo",
    "Luật Ngân sách",
    "Luật Giáo dục",
    "Luật Thủy lợi",
    "Luật Phòng.*tham nhũng",
    "Bộ luật Lao động",
    "nghỉ dưỡng sức",
    "tai nạn lao động",
    "bảo hiểm nông nghiệp",
    "du lịch.*hướng dẫn",
    "kinh doanh lữ hành",
    "cơ sở lưu trú",
    "nhà máy thuốc lá",  # QĐ chuyển đổi DNNN đơn lẻ quá cụ thể
    "xí nghiệp",
    "nhà máy.*thành.*tnhh",
    r"chuyển\s+\w+\s+(nhà máy|xí nghiệp|công ty \w+\s+\w+)\s+thành",
    "phê duyệt phương án.*thuộc.*tỉnh",
    "phê duyệt phương án.*thuộc.*bộ",
    "sắp xếp.*đổi mới.*100%.*vốn nhà nước.*tỉnh",
    "cai nghiện ma túy",
    "an ninh, trật tự.*ngành nghề",
    "điều kiện an ninh, trật tự",
    "xuất bản phẩm",
    "văn hóa.*điều kiện",
    "bình đẳng giới",
    "hải quan",
    "khu kinh tế cửa khẩu",
    "khu kinh tế.*thương mại đặc biệt",
]

# Từ khóa loại trừ khỏi nhóm QĐ-TTg (quá đặc thù)
REJECT_TTG_KEYWORDS = [
    "phê duyệt phương án",
    "phê duyệt đề án.*chuyển.*tổng công ty",
    "phê duyệt đề án.*thành lập.*tập đoàn",
    "thành lập.*công ty mẹ.*tập đoàn",
    "chuyển.*sang.*mô hình.*công ty mẹ",
    "thí điểm.*tổ chức.*hoạt động.*mô hình",
    "phê duyệt.*sắp xếp.*doanh nghiệp.*100%.*vốn",
    "phê duyệt.*cổ phần hóa.*tổng công ty",
]


def check_keywords(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    for kw in keywords:
        if re.search(kw.lower(), t):
            return True
    return False


def get_doc_type(line: str) -> str:
    t = line.lower()
    if re.search(r"nghị định", t):
        return "Nghị định"
    if re.search(r"thông tư", t):
        return "Thông tư"
    if re.search(r"quyết định.*ttg|quyết định.*thủ tướng", t):
        return "Quyết định TTg"
    if re.search(r"quyết định", t):
        return "Quyết định khác"
    if re.search(r"nghị quyết", t):
        return "Nghị quyết"
    if re.search(r"thông báo|công văn|chỉ thị", t):
        return "Khác"
    return "Khác"


def classify(line: str, strict: bool = False) -> str:
    """Trả về 'keep', 'partial', hoặc 'reject'."""
    # Luôn loại bỏ trước
    if check_keywords(line, REJECT_KEYWORDS):
        return "reject"

    # QĐ-TTg đặc thù quá cụ thể
    doc_type = get_doc_type(line)
    if doc_type == "Quyết định TTg" and check_keywords(line, REJECT_TTG_KEYWORDS):
        return "reject"

    # Kiểm tra giữ lại
    if check_keywords(line, KEEP_KEYWORDS):
        return "keep"

    # Liên quan một phần
    if check_keywords(line, PARTIAL_KEYWORDS):
        return "partial"

    # strict mode (l1 lấy từ "Văn bản áp dụng"): mặc định reject nếu không match
    if strict:
        return "reject"

    # Với các file khác: nếu có "doanh nghiệp" trong tên thì giữ lại một phần
    if "doanh nghiệp" in line.lower() or "công ty" in line.lower():
        return "partial"

    return "reject"


def extract_section(lines: list[str], section_name: str) -> list[str]:
    """Trích xuất các dòng thuộc section có tên chứa section_name."""
    result = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(section_name):
            in_section = True
            continue
        if in_section:
            if stripped.startswith("Văn bản") and section_name not in stripped:
                break  # section mới
            if stripped.startswith("- "):
                result.append(stripped)
    return result


def process_file(key: str) -> str:
    meta = LAW_META[key]
    path = DATA_DIR / f"{key}.md"
    lines = path.read_text(encoding="utf-8").splitlines()

    items = extract_section(lines, meta["section"])

    groups = {
        "keep": {"Nghị định": [], "Thông tư": [], "Quyết định TTg": [], "Quyết định khác": [], "Nghị quyết": [], "Khác": []},
        "partial": [],
    }

    for item in items:
        label = classify(item, strict=meta.get("strict", False))
        if label == "keep":
            doc_type = get_doc_type(item)
            groups["keep"][doc_type].append(item)
        elif label == "partial":
            groups["partial"].append(item)
        # reject → bỏ qua

    # ── Build output ──────────────────────────────────────────────────────────
    out = [f"# {meta['title']}", f"**Hiệu lực**: {meta['hieu_luc']}", ""]

    keep_types_order = ["Nghị định", "Thông tư", "Quyết định TTg", "Quyết định khác", "Nghị quyết", "Khác"]
    has_keep = any(groups["keep"][t] for t in keep_types_order)

    if has_keep:
        for doc_type in keep_types_order:
            items_list = groups["keep"][doc_type]
            if items_list:
                out.append(f"## {doc_type} ✅")
                out.extend(items_list)
                out.append("")

    if groups["partial"]:
        out.append("## Văn bản liên quan một phần ⚠️")
        out.extend(groups["partial"])
        out.append("")

    if not has_keep and not groups["partial"]:
        out.append("*(Không có văn bản liên quan sau khi lọc)*")

    # Thống kê
    total_keep = sum(len(v) for v in groups["keep"].values())
    total_partial = len(groups["partial"])
    total_reject = len(items) - total_keep - total_partial
    out.append("---")
    out.append(f"*Thống kê: ✅ {total_keep} | ⚠️ {total_partial} | ❌ bỏ {total_reject} / tổng {len(items)} văn bản*")

    return "\n".join(out)


def main():
    out_dir = DATA_DIR
    for key in LAW_META:
        content = process_file(key)
        out_path = out_dir / f"{key}_filtered.md"
        out_path.write_text(content, encoding="utf-8")
        print(f"OK {key}_filtered.md")

    print("\nXong!")


if __name__ == "__main__":
    main()
