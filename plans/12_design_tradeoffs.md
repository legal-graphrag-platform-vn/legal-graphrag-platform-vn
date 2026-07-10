# Design Trade-offs — Sự Đánh Đổi Kiến Trúc

> **Phiên bản**: 0.1
> **Ngày chốt**: 2026-07-07
> **Depends on**: [legal_ontology.md v1.5.0](./legal_ontology.md)

Tài liệu này đóng vai trò như một "Executive Summary", tổng hợp các quyết định lớn nhất (đã được ghi nhận chi tiết tại `00_architecture_decisions.md`) phục vụ riêng cho việc trình bày và bảo vệ luận văn trước hội đồng. Trong kiến trúc phần mềm, không có giải pháp hoàn hảo, chỉ có sự đánh đổi (trade-offs) phù hợp nhất với context của dự án.

---

## 1. Tại sao dùng Neo4j Vector thay vì Qdrant/Milvus?

*Xem chi tiết: ADR-10*

**Bối cảnh**: Hệ thống cần lưu trữ vector nhúng (embeddings) cho từng `Clause` và thực hiện vector search.
- **Tại sao chọn Neo4j Vector**: Giữ mọi thứ (đồ thị tri thức, metadata, và vector) trong một database duy nhất. Điều này cho phép thực hiện truy vấn RAG lai (hybrid) và duyệt đồ thị (graph traversal) trong một câu lệnh Cypher duy nhất.
- **Sự đánh đổi**: Neo4j Vector chậm hơn và tốn memory hơn so với các specialized vector databases (như Qdrant hay Milvus) khi scale lên hàng triệu vector. Tuy nhiên, với scope đồ án (20 văn bản, khoảng 2000-5000 chunks), sự chênh lệch này là không đáng kể, trong khi giá trị mang lại từ việc dễ quản lý, dễ query, và tính Atomic của data là rất lớn.

## 2. Tại sao dùng Denormalization thay vì FRBR (Snapshot Versioning)?

*Xem chi tiết: ADR-18*

**Bối cảnh**: Cần giải quyết bài toán thời gian (Temporal) — một điều luật có thể bị sửa đổi nhiều lần.
- **Tại sao chọn Denormalization**: Chúng ta gắn trực tiếp `effective_from`, `effective_to`, và `legal_status` lên từng node `Article` và `Clause`. Khi có văn bản sửa đổi (relation `AMENDS`), Neo4j Writer sẽ tự động cập nhật (cascade) các property này. Cách này rất dễ query với half-open interval `WHERE effective_from <= X AND (effective_to IS NULL OR effective_to > X)` và giữ cho đồ thị nhỏ gọn. Convention: `effective_to` là ngày bắt đầu không còn hiệu lực.
- **Sự đánh đổi**: Mất đi khả năng "Time Travel" hoàn hảo (Bitemporal) hoặc xem toàn bộ văn bản tại một thời điểm quá khứ như một thực thể độc lập (FRBR Expression). Nhưng FRBR yêu cầu schema phức tạp gấp 3 lần và chi phí duy trì quá lớn so với nguồn lực của một đồ án, nó phù hợp hơn cho các trang portal tra cứu luật cấp Quốc gia.

## 3. Tại sao Chunk theo Điều/Khoản thay vì Fixed-size Chunk?

*Xem chi tiết: ADR-02*

**Bối cảnh**: Chia nhỏ văn bản để đưa vào RAG (Chunking).
- **Tại sao chọn Điều/Khoản**: Trong ngữ cảnh pháp lý, một "Điều" hoặc "Khoản" là một đơn vị ngữ nghĩa trọn vẹn và mang tính thi hành pháp lý (legal unit). Bằng cách chunk theo cấu trúc này, chúng ta đảm bảo LLM nhận được một quy định trọn vẹn, không bị cắt ngang giữa chừng.
- **Sự đánh đổi**: Độ dài chunk sẽ không đồng đều (có khoản rất dài, có khoản rất ngắn), gây khó khăn nhẹ cho các model embedding vốn tối ưu cho độ dài cố định. Tuy nhiên, giá trị giữ nguyên semantic constraint (tính toàn vẹn của pháp luật) vượt trội hơn nhiều so với việc cắt đứt câu.

## 4. Tại sao cấu trúc Pipeline dạng Single-node thay vì Microservices/RabbitMQ?

**Bối cảnh**: Thiết kế kiến trúc cho quá trình xây dựng Graph (Ingestion Pipeline).
- **Tại sao chọn Single-node**: Toàn bộ quá trình `Crawler` $\rightarrow$ `Parser` $\rightarrow$ `LLM Extraction` $\rightarrow$ `Neo4j Writer` chạy tuần tự trong một architecture đơn giản. Cách này phù hợp hoàn toàn cho mục đích nghiên cứu (Research) để test logic mà không tốn effort vào cấu hình Infrastructure.
- **Sự đánh đổi**: Không thể scale ngang (horizontal scaling) hay xử lý hàng vạn văn bản song song. Trải nghiệm dev cũng kém hơn (nếu lỗi ở Extraction thì phải chạy lại hoặc tự viết logic resume). Đồ án chấp nhận đánh đổi này vì mục tiêu là trả lời RC2 (Graph Construction Framework) chứ không phải là xây dựng High-Availability Data Engineering System. Đây là sự phân định rõ ràng giữa Research và Engineering.

## 5. Tại sao dùng BM25 + Vector trong retrieval, nhưng không bắt BM25 làm main baseline?

*Xem chi tiết: ADR-11*

**Bối cảnh**: Thiết kế Retriever để tìm kiếm `Clause` dựa trên câu hỏi người dùng.
- **Tại sao chọn Hybrid**: Ngôn ngữ pháp lý chứa rất nhiều "từ khóa chính xác" (ví dụ: mã số văn bản `59/2020/QH14`, thuật ngữ cụ thể như `CTCP`). Vector search (ngữ nghĩa) thường bỏ sót các keyword chính xác này, trong khi BM25 (keyword matching) lại rất mạnh. Kết hợp cả hai (Hybrid Retrieval) có thể tăng recall trong proposed system.
- **Baseline chính**: Theo ADR-07, baseline bắt buộc vẫn là Naive Vector RAG. BM25 là optional ablation nếu còn thời gian, không phải baseline bắt buộc.
- **Sự đánh đổi**: Tăng độ phức tạp của hệ thống (phải cấu hình Full-text index trên Neo4j và dùng k-NN + Fulltext trong 1 query Cypher) và tốn tài nguyên tính toán hơn (phải re-rank hoặc combine hai danh sách kết quả). Tuy nhiên, đây là Best Practice hiện tại của RAG.

## 6. Tại sao dùng Neo4j Community Edition thay vì Enterprise?

**Bối cảnh**: Chọn Database Engine.
- **Tại sao chọn Community**: Miễn phí, mã nguồn mở, dễ dàng setup thông qua Docker trên mọi máy tính. Cung cấp đầy đủ các tính năng cốt lõi cần thiết cho đồ án (Cypher, Vector Index, Full-text index, Graph algorithms).
- **Sự đánh đổi**: Thiếu Role-Based Access Control (RBAC), thiếu High Availability (Clustering), và đặc biệt là bị giới hạn một database duy nhất cho mỗi instance. Để vượt qua hạn chế này trong lúc test, chúng ta sử dụng nhiều Docker container song song (Dev environment vs Test environment) thay vì setup Multi-DB trên cùng một instance.

## 7. Tại sao chọn kiến trúc Hybrid GraphRAG thay vì thuần Graph hoặc thuần LLM?

*Xem chi tiết: ADR-19*

**Bối cảnh**: Cần quyết định mức độ biểu diễn tri thức trong Graph (Knowledge Representation Strategy). Nên đưa bao nhiêu logic pháp lý vào Graph?
- **Tại sao chọn Hybrid**: Chúng ta chỉ lưu trữ **Stable Legal Knowledge** (cấu trúc, trích dẫn, khái niệm, thời gian) vào Graph. Toàn bộ **Context-dependent Legal Reasoning** (nghĩa vụ, ngoại lệ, điều kiện, giải thích) được giao cho LLM xử lý tại runtime. 
- **Sự đánh đổi**: 

| Criterion           | Graph | LLM    | Hybrid (GraphRAG) |
| ------------------- | ----- | ------ | ------ |
| Explainability      | High  | Low    | High   |
| Adaptability        | Low   | High   | High   |
| Determinism         | High  | Low    | Medium |
| Ontology complexity | High  | Low    | Medium |
| Retrieval precision | High  | Medium | High   |

- **Kết luận**: Nếu cố gắng mã hóa mọi logic pháp lý vào Graph, ontology sẽ trở nên khổng lồ và cực kỳ khó duy trì (Option Graph-only). Ngược lại, nếu phó mặc hoàn toàn cho LLM tự đọc luật, hệ thống sẽ thiếu tính quyết định và dễ sinh ảo giác (Option LLM-only). **Kiến trúc Hybrid chính là lựa chọn cân bằng**, sử dụng Graph để cung cấp bằng chứng chính xác tuyệt đối, và sử dụng LLM để linh hoạt diễn giải các trường hợp thực tế phức tạp.
