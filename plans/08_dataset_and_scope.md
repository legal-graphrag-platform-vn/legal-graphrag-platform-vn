# Dataset & Scope

> **Domain**: Pháp luật doanh nghiệp Việt Nam  
> **Phạm vi**: Luật Doanh nghiệp 2020 + các văn bản hướng dẫn

---

## Phạm Vi Dữ Liệu

### Cấu Trúc Hệ Thống Văn Bản (Target)

```
Luật Doanh nghiệp 2020 (59/2020/QH14)
         │
         ├── GUIDES ──→ NĐ 01/2021/NĐ-CP (Đăng ký DN)
         │                          │
         │                          └── GUIDES ──→ TT 01/2021/TT-BKHĐT
         │
         ├── GUIDES ──→ NĐ 47/2021/NĐ-CP (Sửa đổi NĐ 01)
         │
         ├── GUIDES ──→ NĐ 155/2020/NĐ-CP (Chứng khoán - DN đại chúng)
         │
         └── AMENDS ──→ Luật Doanh nghiệp 2014 (tiền thân)
```

---

## Curated Research Corpus (Đã Chốt)

Corpus được chia thành các phạm vi độc lập để không đánh đồng dữ liệu đã crawl
với dữ liệu được kiểm soát chất lượng cho nghiên cứu:

| Phạm vi | Quy mô | Mục đích |
|---|---:|---|
| Crawl/discovery pool | 89 văn bản tại thời điểm chốt | Nguồn ứng viên; có thể thay đổi và không mặc định được ingest/evaluate |
| Curated research corpus | 10 văn bản | Phạm vi chính thức cho graph construction, retrieval và QA evaluation |
| Minimum demo corpus | 4 văn bản cốt lõi | Mốc tối thiểu nếu thiếu thời gian |
| Gold graph corpus | 3 văn bản thuộc curated corpus | Annotation thủ công cho Graph Construction Quality |

Chỉ curated corpus được tính vào scope nghiên cứu. Crawl pool là runtime data có
thể tái tạo, nằm dưới `data/`, và không được commit vào Git.

### Nhóm 1 — Văn Bản Cốt Lõi (BẮT BUỘC)

| STT | Số Hiệu | Tên Văn Bản | Loại | Ghi Chú |
|---|---|---|---|---|
| 1 | 59/2020/QH14 | Luật Doanh nghiệp 2020 | Luật | Main law |
| 2 | 01/2021/NĐ-CP | NĐ về đăng ký doanh nghiệp | NĐ | Hướng dẫn chính |
| 3 | 47/2021/NĐ-CP | NĐ sửa đổi NĐ 01/2021 | NĐ | Temporal test |
| 4 | 01/2021/TT-BKHĐT | TT hướng dẫn đăng ký DN | TT | Hướng dẫn NĐ 01 |

### Nhóm 2 — Curated Mở Rộng

| STT | Số Hiệu | Tên Văn Bản | Loại | Ghi Chú |
|---|---|---|---|---|
| 5 | 68/2014/QH13 | Luật Doanh nghiệp 2014 | Luật | Temporal: trước 2020 |
| 6 | 78/2015/NĐ-CP | NĐ đăng ký DN 2015 | NĐ | Temporal: trước 2021 |
| 7 | 108/2018/NĐ-CP | NĐ sửa đổi NĐ 78/2015 | NĐ | Temporal: 2018-2020 |
| 8 | 155/2020/NĐ-CP | NĐ về chứng khoán/DN đại chúng | NĐ | Mở rộng |
| 9 | 61/2020/QH14 | Luật Đầu tư 2020 | Luật | Related law |
| 10 | 31/2021/NĐ-CP | NĐ chi tiết Luật Đầu tư | NĐ | Liên quan |

> **Scope chính thức**: 10 văn bản curated
>
> **Minimum demo**: 4 văn bản cốt lõi
>
> **Gold annotation**: 3 văn bản thuộc curated corpus
>
> **Crawl pool không phải evaluation scope** và không thay đổi giới hạn curated corpus.

---

## Ground Truth Dataset

### Phần 1 — Gold Graph Annotation
**Mục đích**: Đánh giá chất lượng Graph Construction (RC5, Level 1)  
**Số lượng**: Annotate thủ công **3 văn bản** (NĐ 01/2021 là trọng tâm)  
**Format**:

```json
{
  "document": "ND01_2021",
  "entities": [
    {
      "id": "nd_01_2021_art5",
      "type": "Article",
      "label": "Điều 5. Hồ sơ đăng ký doanh nghiệp",
      "properties": {
        "effective_from": "2021-01-04",
        "legal_status": "ACTIVE"
      }
    }
  ],
  "relations": [
    {
      "head": "nd_01_2021",
      "relation": "CONTAINS",
      "tail": "nd_01_2021_art5"
    },
    {
      "head": "ldn_2020_art26",
      "relation": "REFERS_TO",
      "tail": "nd_01_2021_art5",
      "properties": {
        "citation_text": "theo Điều 5 Nghị định 01/2021/NĐ-CP",
        "citation_type": "DIRECT"
      }
    }
  ]
}
```

### Phần 2 — QA Dataset
**Mục đích**: Đánh giá Retrieval + QA quality (RC5, Level 2-3)

**Scope chuẩn hóa:**

- Current committed scope: **50 general QA + 25 temporal QA**
- Target full scope nếu đủ thời gian: **100 general QA + 50 temporal QA**
- Minimum accepted scope: **50 general QA + 25 temporal QA**

**Cấu trúc target full 100 câu hỏi general QA:**

| Loại | Số Lượng | Ví Dụ |
|---|---|---|
| Factual | 40 | "Điều kiện để thành lập công ty TNHH là gì?" |
| Hierarchy | 20 | "Nghị định nào hướng dẫn Điều 26 Luật DN 2020?" |
| Multi-hop | 20 | "Thủ tục đăng ký DN theo NĐ 01/2021 yêu cầu những gì?" |
| Definition | 20 | "Vốn pháp định là gì theo quy định hiện hành?" |

**Format:**
```json
{
  "id": "QA_001",
  "question": "Điều kiện để thành lập công ty TNHH hai thành viên là gì?",
  "answer": "Theo Điều 46 Luật Doanh nghiệp 2020...",
  "relevant_articles": ["ldn_2020_art46", "ldn_2020_art29"],
  "difficulty": "medium"
}
```

### Phần 3 — Temporal QA Dataset
**Mục đích**: Đánh giá Temporal Accuracy (RC5, Level 4)

**Cấu trúc target full 50 câu hỏi temporal:**

| Loại | Số Lượng | Ví Dụ |
|---|---|---|
| Point-in-time | 20 | "Năm 2019, thủ tục đăng ký DN quy định thế nào?" |
| Before/After | 15 | "Sau khi NĐ 47/2021 có hiệu lực, quy định về vốn thay đổi gì?" |
| Validity check | 15 | "NĐ 78/2015 còn hiệu lực tại thời điểm 2022 không?" |

**Format:**
```json
{
  "id": "TQA_001",
  "question": "Năm 2019, thủ tục đăng ký doanh nghiệp theo quy định nào?",
  "temporal_context": {
    "year": 2019,
    "from": "2019-01-01",
    "to": "2019-12-31"
  },
  "answer": "Năm 2019, áp dụng NĐ 78/2015 (NĐ 108/2018 sửa đổi)...",
  "relevant_articles": ["nd_78_2015_art8", "nd_108_2018_art1"],
  "should_not_use": ["nd_01_2021_art5"]
}
```

### Phần 4 — XAI Evaluation
**Mục đích**: Đánh giá Citation Completeness + Reasoning Path (RC5, Level 4)

**20-30 câu** với expected reasoning path:

```json
{
  "id": "XAI_001",
  "question": "Công ty TNHH phải có bao nhiêu thành viên?",
  "expected_answer": "Từ 2 đến 50 thành viên",
  "expected_citations": ["ldn_2020_art46_cl1"],
  "expected_path": [
    "ldn_2020_art46",
    "CONTAINS",
    "ldn_2020_art46_cl1",
    "DEFINES",
    "LegalConcept(\"Số thành viên tối thiểu\")"
  ]
}
```

---

## Câu Hỏi Mở Cho Nhóm

| # | Câu Hỏi | Ai Quyết Định |
|---|---|---|
| 1 | Danh sách 10 văn bản có đúng không? | Cả nhóm |
| 2 | Có thể thu thập được các NĐ cũ (2015, 2018)? | Người phụ trách data |
| 3 | Ai phụ trách annotate Gold Graph (3 văn bản)? | Cả nhóm |
| 4 | Ai viết 100 QA pairs? Phân chia thế nào? | Cả nhóm |
| 5 | Có mời legal expert review dataset không? | Leader quyết |
