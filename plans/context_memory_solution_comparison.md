# Bài toán Context Memory trong Legal GraphRAG

> **Loại tài liệu**: Phân tích giải pháp và lựa chọn kiến trúc  
> **Phạm vi**: Context memory cho hội thoại hỏi đáp pháp luật  
> **Mức trình bày**: Ý tưởng kiến trúc, không đi vào code hoặc kế hoạch triển khai  
> **Trạng thái**: Đề xuất

## 1. Bài toán

Hệ thống Legal GraphRAG hiện có thể xử lý tốt một câu hỏi pháp lý độc lập, nhưng
gặp khó khăn khi người dùng đặt câu hỏi nối tiếp và lược bỏ thông tin đã xuất
hiện ở lượt trước.

Ví dụ:

> Người dùng: Điều 17 Luật Doanh nghiệp quy định những ai không được thành lập
> doanh nghiệp?  
> Người dùng: Còn khoản 2 thì sao?  
> Người dùng: Quy định đó hiện còn hiệu lực không?

Hai câu sau không đủ thông tin để retrieval nếu tách khỏi hội thoại:

- “khoản 2” chưa chỉ rõ thuộc Điều nào và văn bản nào;
- “quy định đó” chưa chỉ rõ đơn vị pháp luật cần kiểm tra;
- “hiện còn hiệu lực” cần kết hợp đúng đối tượng với thời điểm hiện tại;
- một correction như “ý tôi là công ty cổ phần” cần thay subject cũ nhưng không
  được làm mất các phần context còn hợp lệ.

Context memory cần giúp hệ thống hiểu người dùng đang nói đến đối tượng nào,
nhưng không được trở thành một nguồn pháp luật thay thế cho retrieval và
grounding.

## 2. Cách đặt lại vấn đề

How Might We:

> Làm thế nào để Legal GraphRAG hiểu chính xác các câu hỏi nối tiếp, đồng thời
> không sử dụng lịch sử hội thoại như căn cứ pháp luật và không làm suy yếu cơ
> chế citation, temporal validation và grounding hiện có?

Người dùng mục tiêu là người tra cứu pháp luật theo dạng hội thoại, thường hỏi
tiếp về cùng một văn bản, Điều, Khoản, chủ thể hoặc trạng thái hiệu lực.

Một giải pháp thành công cần đạt được các kết quả sau:

- hiểu đúng tham chiếu như “điều đó”, “khoản trên”, “đối tượng này”;
- tạo được câu hỏi độc lập trước retrieval;
- không mang nhầm context khi người dùng chuyển chủ đề;
- không coi answer cũ hoặc memory là legal evidence;
- mỗi câu trả lời pháp lý vẫn dựa trên evidence được retrieval cho lượt hiện tại;
- giải thích được context nào đã được sử dụng;
- xử lý an toàn khi context mơ hồ, hết hạn hoặc bị cập nhật đồng thời.

## 3. Các nguyên tắc không được phá vỡ

### Memory chỉ làm rõ truy vấn

Memory được dùng để xác định document, article, clause hoặc subject mà người dùng
đang nói đến. Nó không được dùng trực tiếp để chứng minh một kết luận pháp lý.

### Mỗi legal query phải retrieval lại

Việc một Điều đã xuất hiện ở lượt trước không đảm bảo nội dung đó đủ hoặc còn phù
hợp cho câu hỏi mới. Legal evidence phải được lấy và kiểm tra lại.

### Grounding vẫn là cửa kiểm soát cuối

Mọi legal claim phải có citation hợp lệ. Memory không được bổ sung citation hoặc
làm cho một answer thiếu evidence trở nên hợp lệ.

### Temporal context không được kế thừa tùy tiện

Ngày của câu hỏi trước không tự động áp dụng cho câu hỏi sau. Thời điểm phải đến
từ yêu cầu hiện tại hoặc được temporal parser xác định theo quy tắc hiện có.

### Khi mơ hồ thì hỏi lại

Chọn sai document hoặc Điều trong lĩnh vực pháp luật nguy hiểm hơn việc yêu cầu
người dùng làm rõ. Hệ thống phải fail closed khi có nhiều cách hiểu hợp lý.

## 4. Tiêu chí đánh giá giải pháp

Các phương án được so sánh trên bảy tiêu chí:

1. **Độ chính xác ngữ cảnh**: khả năng resolve đúng tham chiếu hội thoại.
2. **An toàn pháp lý**: mức độ tách biệt giữa memory và legal evidence.
3. **Khả năng giải thích**: có biết hệ thống đã dùng context nào và vì sao không.
4. **Khả năng kiểm soát**: có thể đặt rule cho TTL, reset, precedence và ambiguity.
5. **Chi phí vận hành**: token, model call, storage và latency.
6. **Độ phức tạp**: số component và mức khó khi bảo trì.
7. **Khả năng tích hợp**: mức phù hợp với retrieval và grounding pipeline hiện có.

## 5. Phương án 1 — Gửi toàn bộ lịch sử hội thoại cho LLM

### Ý tưởng

Mỗi lượt hỏi sẽ gửi toàn bộ các message trước đó cho một LLM. Model tự đọc lịch
sử, tự suy ra câu hỏi hiện tại đang tham chiếu đến nội dung nào và tạo câu trả
lời.

### Ưu điểm

- đơn giản về mặt ý tưởng;
- gần với cách các chatbot thông thường hoạt động;
- giữ được nhiều sắc thái và cách diễn đạt của người dùng;
- không cần thiết kế state schema ngay từ đầu;
- phù hợp cho prototype hội thoại ngắn và ít yêu cầu kiểm soát.

### Nhược điểm

- chi phí token tăng theo độ dài hội thoại;
- latency tăng và khó dự đoán;
- lịch sử có thể chứa answer sai, thông tin cũ hoặc prompt injection;
- LLM có thể lựa chọn nhầm referent mà không có dấu hiệu rõ ràng;
- khó biết chính xác phần nào của history đã ảnh hưởng đến query;
- không giải quyết triệt để việc retrieval cần một câu hỏi rõ nghĩa trước khi
  answer model chạy;
- dễ làm lẫn memory với legal evidence;
- không có cơ chế TTL hoặc cascade reset xác định.

### Đánh giá

Phương án này phù hợp cho chatbot tổng quát nhưng không phù hợp làm kiến trúc
chính của Legal GraphRAG, nơi retrieval scope và provenance phải kiểm soát được.

## 6. Phương án 2 — Sliding window của một số lượt gần nhất

### Ý tưởng

Thay vì gửi toàn bộ history, hệ thống chỉ giữ một số message gần nhất, chẳng hạn
hai hoặc ba cặp hỏi đáp.

### Ưu điểm

- đơn giản hơn full history;
- giới hạn được token và latency;
- loại bỏ tự nhiên các message quá cũ;
- đủ dùng cho các follow-up rất gần như “còn khoản 2 thì sao?”.

### Nhược điểm

- việc cắt theo số message không phản ánh vòng đời ngữ nghĩa của context;
- một anchor quan trọng có thể bị loại chỉ vì đã nằm ngoài cửa sổ;
- một topic cũ vẫn có thể bị giữ dù người dùng đã chuyển chủ đề;
- vẫn gửi raw text không có canonical identity;
- vẫn phụ thuộc vào LLM tự hiểu document/article/clause;
- khó áp dụng precedence giữa thông tin hiện tại và history;
- không giải quyết tốt concurrent request hoặc session persistence.

### Đánh giá

Sliding window cải thiện chi phí nhưng không giải quyết bản chất của bài toán.
Nó là một kỹ thuật giới hạn context, không phải một mô hình memory đáng tin cậy.

## 7. Phương án 3 — LLM-generated conversation summary

### Ý tưởng

Sau mỗi lượt, LLM tạo hoặc cập nhật một bản tóm tắt hội thoại. Lượt sau chỉ nhận
summary thay vì toàn bộ history.

Ví dụ summary có thể ghi rằng người dùng đang hỏi về Luật Doanh nghiệp, Điều 17,
chủ thể là công ty cổ phần và quan tâm đến hiệu lực hiện tại.

### Ưu điểm

- giảm đáng kể token so với full history;
- giữ được context dài hạn tốt hơn sliding window;
- summary có thể chứa topic, mục tiêu và preference khó biểu diễn bằng vài field;
- trải nghiệm hội thoại tự nhiên hơn khi chủ đề kéo dài.

### Nhược điểm

- summary là output của LLM nên có thể sai hoặc làm mất chi tiết;
- lỗi summary có xu hướng tích lũy qua nhiều lượt;
- khó phân biệt điều user thực sự nói với suy diễn của model;
- khó kiểm tra canonical ID và hierarchy;
- một summary stale có thể tiếp tục ảnh hưởng nhiều query sau;
- việc sửa một phần summary mà không làm hỏng phần còn lại khá khó;
- vẫn có nguy cơ summary bị sử dụng như legal evidence;
- cần thêm model call hoặc tăng latency cho mỗi lượt.

### Đánh giá

Summary memory hữu ích cho mục tiêu, preference hoặc hội thoại mở. Với legal
anchors cần độ chính xác cao, nó không nên là nguồn context chính. Nếu sử dụng,
nó chỉ nên là lớp phụ trợ không có quyền tạo filter hoặc canonical ID.

## 8. Phương án 4 — Structured slot memory

### Ý tưởng

Hệ thống chỉ lưu một tập field có cấu trúc, ví dụ:

- document đang được nói đến;
- article và clause đang được tập trung;
- subject pháp lý hiện tại;
- lượt grounded gần nhất;
- thời điểm thiết lập và hạn sử dụng của từng field.

Các field chỉ chứa canonical identity đã được resolve, không lưu raw text như ID.

### Ưu điểm

- context rõ ràng và dễ giải thích;
- dễ kiểm tra hierarchy document–article–clause;
- có thể áp dụng TTL, precedence và cascade reset xác định;
- chi phí storage và token thấp;
- dễ giới hạn dữ liệu nhạy cảm;
- phù hợp với ontology và metadata citation hiện có;
- dễ kiểm soát việc memory có được dùng làm filter hay chỉ là query hint;
- hành vi có thể test và quan sát bằng reason code.

### Nhược điểm

- không giữ tốt sắc thái hội thoại tự do;
- phải dự đoán trước các loại context cần lưu;
- gặp khó với câu hỏi phức tạp chứa nhiều giả thuyết song song;
- cần component resolve mention thành canonical ID;
- cần quy tắc rõ cho trường hợp answer cite nhiều document hoặc article;
- schema có thể phải mở rộng khi sản phẩm hỗ trợ domain mới.

### Đánh giá

Đây là phương án mạnh cho phần legal focus vì có tính xác định, nhỏ gọn và dễ
audit. Tuy nhiên, structured state tự nó chưa đủ: hệ thống vẫn cần biến follow-up
thành standalone query trước retrieval.

## 9. Phương án 5 — Vector-based episodic memory

### Ý tưởng

Mỗi lượt hội thoại hoặc một số sự kiện quan trọng được embedding và lưu vào
vector store. Khi có query mới, hệ thống semantic-search các lượt cũ liên quan rồi
đưa chúng vào context.

### Ưu điểm

- tìm lại được context cũ ngay cả khi cách diễn đạt thay đổi;
- hỗ trợ hội thoại dài tốt hơn sliding window;
- không cần một schema cố định cho mọi loại memory;
- phù hợp với preference, sự kiện hoặc chủ đề mở;
- có thể mở rộng thành memory qua nhiều session.

### Nhược điểm

- semantic similarity không đảm bảo referent chính xác;
- top-k memory có thể đưa sai topic vào query hiện tại;
- khó áp dụng hierarchy và hard legal constraints;
- retrieval memory và retrieval legal evidence trở thành hai pipeline dễ bị nhầm;
- cần thêm embedding, index, storage và ranking policy;
- kết quả khó giải thích hơn structured anchors;
- raw conversation được lưu lâu hơn, làm tăng rủi ro privacy;
- không giải quyết tốt correction hoặc cascade reset.

### Đánh giá

Vector memory phù hợp cho long-term personal assistant hơn là context ngắn hạn
có cấu trúc của Legal GraphRAG. Nó có thể là future extension, nhưng không nên là
cơ chế chính cho document/article/clause resolution.

## 10. Phương án 6 — Conversation Knowledge Graph

### Ý tưởng

Biểu diễn hội thoại thành một graph riêng gồm turn, topic, user mention, legal
anchor, correction và quan hệ tham chiếu. Hệ thống traversal graph hội thoại để
resolve context cho query mới.

### Ưu điểm

- biểu diễn được nhiều nhánh, nhiều giả thuyết và quan hệ phức tạp;
- provenance của từng anchor có thể rất chi tiết;
- hỗ trợ conversation branching và long-term reasoning;
- phù hợp nếu hệ thống trở thành một legal research workspace lớn;
- có thể giải thích đường đi từ message hiện tại đến context cũ.

### Nhược điểm

- phức tạp quá mức cho bài toán follow-up cơ bản;
- cần schema, lifecycle, cleanup và traversal policy riêng;
- dễ gây nhầm lẫn với Legal Knowledge Graph;
- authorization và retention khó hơn;
- chi phí phát triển, vận hành và debug cao;
- chưa có nhu cầu thực tế đủ mạnh để biện minh cho độ phức tạp;
- nguy cơ biến contextual inference thành dữ liệu persisted lâu dài.

### Đánh giá

Đây là hướng có trần năng lực cao nhất nhưng feasibility thấp nhất trong phạm vi
đồ án. Nó phù hợp với future work hơn là giải pháp hiện tại.

## 11. Phương án 7 — Hybrid grounded structured memory

### Ý tưởng

Kết hợp structured slot memory với một lớp follow-up query resolution và cơ chế
commit sau grounding:

1. Memory lưu canonical document/article/clause/subject anchors và một lượt
   grounded gần nhất.
2. Resolver đọc memory, loại anchor hết hạn và phát hiện correction.
3. Rewriter dùng structured context để tạo standalone query.
4. Pipeline retrieval hiện có chạy lại cho legal query mới.
5. Answer tiếp tục qua citation và grounding validation.
6. Chỉ các citation thực sự được dùng mới cập nhật legal-unit focus.
7. State được ghi bằng atomic compare-and-set.

### Ưu điểm

- kế thừa tính xác định và khả năng audit của structured memory;
- giải quyết đúng điểm thiếu của structured slots bằng standalone query rewrite;
- giữ memory tách khỏi legal evidence;
- tương thích với retrieval và grounding pipeline hiện có;
- không thay đổi trách nhiệm của intent router hoặc query planner;
- chỉ used citations mới ảnh hưởng lượt sau;
- TTL và cascade reset hạn chế stale context;
- ambiguity có thể fail closed;
- CAS ngăn lost update khi có request đồng thời;
- chi phí thấp hơn full history, vector memory và conversation graph;
- đủ đơn giản cho đồ án nhưng vẫn có đường mở rộng.

### Nhược điểm

- nhiều component hơn sliding window hoặc summary đơn giản;
- cần thiết kế rule cho precedence, expiry và citation-derived focus;
- rewriter vẫn có thể hiểu sai nếu input ambiguous;
- structured state không giữ toàn bộ sắc thái hội thoại;
- cần canonical linker cho subject và legal units;
- output-meta cần re-fetch evidence của lượt trước thay vì chỉ dùng answer text.

### Đánh giá

Phương án này không mạnh nhất ở mọi tiêu chí riêng lẻ, nhưng có cân bằng tốt nhất
giữa độ chính xác, an toàn pháp lý, khả năng giải thích, chi phí và mức phù hợp
với kiến trúc hiện tại.

## 12. Bảng so sánh tổng hợp

| Phương án | Chính xác context | An toàn pháp lý | Giải thích | Chi phí | Độ phức tạp | Phù hợp hệ thống hiện tại |
|---|---|---|---|---|---|---|
| Full history | Trung bình | Thấp | Thấp | Cao | Thấp | Thấp |
| Sliding window | Trung bình-thấp | Thấp | Thấp | Trung bình | Thấp | Trung bình-thấp |
| LLM summary | Trung bình | Trung bình-thấp | Trung bình-thấp | Trung bình | Trung bình | Trung bình |
| Structured slots | Cao | Cao | Cao | Thấp | Trung bình | Cao |
| Vector episodic memory | Trung bình | Trung bình-thấp | Thấp | Cao | Cao | Trung bình-thấp |
| Conversation graph | Cao | Cao nếu làm đúng | Cao | Cao | Rất cao | Thấp trong phạm vi đồ án |
| Hybrid grounded structured memory | Cao | Rất cao | Cao | Trung bình-thấp | Trung bình | Rất cao |

## 13. Giải pháp được lựa chọn

Chọn **Hybrid Grounded Structured Memory**.

Lý do quan trọng nhất không phải vì đây là phương án nhiều tính năng nhất, mà vì
nó giải quyết đúng tension của Legal GraphRAG:

> Hệ thống cần nhớ đủ để hiểu câu hỏi, nhưng không được tin memory như một nguồn
> luật.

Structured anchors cung cấp context rõ ràng. Follow-up rewriter biến context đó
thành standalone query. Retrieval và grounding hiện có tiếp tục bảo vệ legal
answer. Post-grounding commit đảm bảo chỉ context đã đi qua một lượt trả lời hợp
lệ mới ảnh hưởng tới hội thoại sau.

Giải pháp tối ưu được mô tả ở mức ý tưởng như sau:

```text
User Message
-> Load Structured Conversation State
-> Classify Standalone / Follow-up / Output-meta
-> Resolve Canonical Context và Expiration
-> Rewrite thành Standalone Query
-> Existing Intent + Temporal + Retrieval Pipeline
-> Existing Evidence + Grounding Pipeline
-> Derive New Focus từ Used Citations
-> Atomic State Commit
```

## 14. Các quy tắc quan trọng của phương án chọn

### Precedence

Thông tin user nói rõ ở lượt hiện tại luôn ưu tiên hơn memory. Sau đó mới đến
canonical context resolve từ current message, rồi mới đến anchor còn hạn.

### Expiration

Mỗi anchor có TTL. Anchor hết hạn bị loại trước khi tạo standalone query.

### Cascade reset

- đổi document thì bỏ article và clause cũ;
- đổi article thì bỏ clause cũ;
- correction subject thì bỏ local focus không còn phù hợp;
- nhiều document không có primary scope thì không tự chọn một document.

### Temporal safety

Ngày của lượt trước không tự động trở thành ngày của lượt sau. “Hiện còn hiệu
lực” phải được temporal parser xử lý lại theo query hiện tại.

### Grounded commit

Answer không đủ evidence, `cannot_answer` hoặc grounding failure không được cập
nhật legal anchors.

### Ambiguity

Khi “văn bản đó” hoặc “điều trên” có nhiều referent hợp lý, hệ thống yêu cầu user
làm rõ thay vì chọn theo rank hoặc vị trí gần nhất.

## 15. Các giả định cần được kiểm chứng

- Phần lớn follow-up trong phạm vi đồ án có thể biểu diễn bằng document, article,
  clause và subject anchors.
- Người dùng chấp nhận clarification khi reference không rõ ràng.
- Metadata trong grounded citations đủ để suy ra hierarchy focus đáng tin cậy.
- Standalone query rewriting cải thiện retrieval mà không làm đổi ý người dùng.
- Một previous grounded turn là đủ cho output-meta trong phạm vi cơ bản.
- Chi phí thêm của resolution/rewriting thấp hơn lợi ích về follow-up accuracy.

Nếu giả định đầu tiên sai và hội thoại thực tế chứa nhiều nhánh hoặc giả thuyết
song song, structured memory có thể cần được mở rộng hoặc bổ sung conversation
graph ở giai đoạn sau.

## 16. Những gì không lựa chọn ở giai đoạn này

- Không dùng full history làm nguồn context mặc định vì tốn token và khó audit.
- Không dùng LLM summary làm legal anchor vì summary có thể tích lũy lỗi.
- Không dùng vector memory làm hard retrieval scope vì similarity không đảm bảo
  identity.
- Không xây conversation graph vì phức tạp vượt quá nhu cầu hiện tại.
- Không lưu conversation state vào Legal Knowledge Graph vì session state không
  phải tri thức pháp luật ổn định.
- Không để query planner xử lý mọi follow-up vì sai trách nhiệm hiện có.
- Không kế thừa query date ngầm giữa các lượt.
- Không cập nhật memory từ top retrieval result nếu unit đó không được citation.

## 17. Rủi ro còn lại của giải pháp chọn

### Rewriter làm thay đổi ý nghĩa câu hỏi

Giảm thiểu bằng structured output, giữ nguyên explicit facts và trả ambiguity khi
không chắc chắn.

### Canonical linker chọn sai entity

Giảm thiểu bằng threshold/margin đã hiệu chỉnh, candidate explanation và typed
clarification thay vì fallback tùy tiện.

### Memory giữ topic quá lâu

Giảm thiểu bằng TTL, explicit-input precedence và cascade reset.

### Citation-derived focus vẫn có nhiều ứng viên

Giảm thiểu bằng quy tắc không tự chọn local focus khi citations trải trên nhiều
article hoặc document.

### Request đồng thời làm mất cập nhật

Giảm thiểu bằng atomic compare-and-set và không retry mù một answer được tạo từ
state cũ.

## 18. Kết luận

Không có một kỹ thuật memory đơn lẻ nào đồng thời tối ưu cho hội thoại tự nhiên,
độ chính xác pháp lý, chi phí thấp và khả năng giải thích.

Full history và summary đơn giản nhưng khó kiểm soát. Vector memory linh hoạt
nhưng không đủ chính xác cho canonical legal references. Conversation graph mạnh
nhưng quá phức tạp. Structured slots an toàn nhưng cần thêm query rewriting để
hoàn chỉnh trải nghiệm follow-up.

Vì vậy, giải pháp phù hợp nhất cho Legal GraphRAG là:

> **Structured Context Memory + Canonical Resolution + Standalone Query Rewrite
> + Per-turn Legal Retrieval + Grounded Citation-based Commit + CAS Storage.**

Giải pháp này cho phép hệ thống nhớ đủ để hiểu người dùng, nhưng buộc mọi kết luận
pháp lý phải quay lại evidence hiện tại. Đây là điểm cân bằng tốt nhất giữa trải
nghiệm hội thoại và độ tin cậy của một hệ thống hỏi đáp pháp luật.
