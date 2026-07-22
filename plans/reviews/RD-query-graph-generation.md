# Technical design: Bổ sung bộ lập kế hoạch đường đi cho câu hỏi pháp lý nhiều bước

> **Mục tiêu của thay đổi:** giúp hệ thống trả lời câu hỏi phải lần theo 2–3 quan hệ
> trên Knowledge Graph, nhưng chỉ khi tìm được đúng đường đi có thật và đủ evidence
> để trích dẫn.
>
> Người cần hiểu solution chỉ cần đọc Phần 1–6. Phần 7 là contract dành cho người
> triển khai.

---

## Tóm tắt trong 5 dòng

- **Vấn đề:** hệ thống trả lời tốt câu hỏi đơn giản, nhưng câu hỏi *nhiều bước* thì **luôn từ chối trả lời**.
- **Nguyên nhân:** code có sẵn phần "kiểm tra đường đi", nhưng **thiếu phần "vạch đường đi"** từ câu hỏi.
- **Giải pháp:** thêm một tầng lập kế hoạch — **AI mô tả cần đi qua đâu, máy tự dò đường thật trên graph**, mọi đường phải được xác minh trước khi trả lời.
- **Phạm vi:** chỉ làm ở lúc truy vấn (read path); **không** sửa cách xây graph (extraction).
- **Điều kiện:** graph phải thật sự chứa dữ liệu nhiều bước — nếu không, phải sửa khâu tạo graph trước (Phần 6).

---

## Thay đổi này khác hệ thống hiện tại ở đâu?

| Hiện tại | Sau thay đổi |
|---|---|
| Query multi-hop không có mô tả đường cần tìm | Planner tạo một kế hoạch đường đi có thứ tự |
| Graph expansion tìm đường chung theo intent | Executor chỉ tìm đúng pattern đã lập kế hoạch |
| Generation không nhận được requirement đáng tin cậy nên phải từ chối | Chỉ plan đã bind và chạy thành công mới tạo requirement |
| Gate chỉ biết số bước và tập loại quan hệ | Gate kiểm đúng đường đã thỏa plan bằng path fingerprint |
| Không biết lỗi nằm ở query hay dữ liệu | Reason code chỉ ra lỗi ở Planner, EntityLinker, Executor hoặc graph |

Nói ngắn gọn:

    Trước: câu hỏi -> tìm kiếm chung -> thiếu yêu cầu suy luận -> từ chối
    Sau:   câu hỏi -> lập kế hoạch -> gắn node thật -> chạy đúng đường
             -> kiểm evidence -> trả lời hoặc từ chối có lý do

---

## Phần 1 — Vấn đề đang gặp

### 1.1. Câu hỏi nhiều bước bị từ chối

Ví dụ đã có gold path được reviewer approve trong bộ evaluation:

> *“Từ quy định về cuộc họp lần thứ ba tại Khoản 3 Điều 145, hãy lần theo các
> dẫn chiếu để xác định điều kiện của lần họp thứ hai và lần họp thứ nhất.”*

Để trả lời, hệ thống phải đi **nhiều chặng** trên đồ thị:

    Khoản 3 Điều 145
      -> REFERS_TO -> Khoản 2 Điều 145
      -> REFERS_TO -> Khoản 1 Điều 145

Đường đã được xác nhận trong graph:

    ldn_2020_art145_cl3
      -> REFERS_TO -> ldn_2020_art145_cl2
      -> REFERS_TO -> ldn_2020_art145_cl1

Nguồn kiểm chứng: `configs/evaluation/retrieval_pilot_l59_2020.json`, case
`multi_hop_02`.

Hiện tại retrieval có thể mở rộng graph, nhưng answer generation không nhận được
một yêu cầu suy luận có thứ tự và đáng tin cậy cho riêng câu hỏi này. Vì vậy hệ
thống fail-closed và trả về “không đủ căn cứ”.

### 1.2. Vì sao nó bỏ cuộc (nguyên nhân kỹ thuật)

Trong code hiện tại:

- **Đã có** một "người kiểm tra" (`sufficiency.py`): kiểm xem một đường đi có hợp lệ, đủ điều kiện không.
- Người kiểm tra này cần một **"đơn yêu cầu"** (tên kỹ thuật: `GraphReasoningRequirement`) — mô tả "cần đi mấy bước, qua quan hệ nào".
- **Nhưng không có ai tạo ra đơn yêu cầu đó** trên đường chạy thật. Không có đơn → không có gì để kiểm → hệ thống mặc định **từ chối**.

> **Đây chính là lỗ hổng giải pháp lấp: xây "người tạo đơn yêu cầu" còn thiếu.**

### 1.3. Chỉ thêm requirement là chưa đủ

Cách tìm kiếm hiện tại mở rộng đồ thị theo policy chung của intent. Nó chưa biểu
diễn đầy đủ: bắt đầu từ node nào, thứ tự quan hệ là gì, đi đúng chiều nào và loại
node đích là gì.

Nếu chỉ tạo `GraphReasoningRequirement` nhưng vẫn dùng phép kiểm không có thứ tự,
một generic path có cùng tập relation type có thể mở gate dù không phải đường mà
query yêu cầu. Vì vậy producer mới phải đi kèm **exact ordered path execution** và
**exact satisfied-path membership**.

---

## Phần 2 — Ý tưởng giải pháp

### 2.1. Nguyên tắc: chia việc cho đúng người

Điểm cốt lõi — **không bắt AI làm việc nó dở**:

| Việc | Ai làm | Vì sao |
|---|---|---|
| Hiểu câu hỏi tiếng Việt muốn gì | **AI (LLM)** | AI giỏi hiểu ngôn ngữ |
| Biết đường nào **có thật** trên graph, ngắn nhất bao nhiêu | **Máy dò đường** | Chỉ database mới biết dữ liệu thật |

Nếu bắt AI tự đoán "đi node A→B→C" thì nó **bịa**, vì nó không nhìn thấy graph. Nên AI chỉ mô tả **yêu cầu (ràng buộc)**, còn **đường đi cụ thể để máy dò**.

### 2.2. Bốn thành phần của giải pháp

| Thành phần | Nhận vào | Trả ra | Không được làm |
|---|---|---|---|
| **1. Planner (LLM)** | Câu hỏi tiếng Việt | Pattern quan hệ có thứ tự | Không sinh node ID, không sinh Cypher |
| **2. EntityLinker** | Cụm neo trong plan | Candidate node ID có thật | Không tự chọn khi kết quả mơ hồ |
| **3. Exact-path Executor** | Plan đã bind | Các path thật thỏa đúng pattern | Không nới constraint để cố tìm kết quả |
| **4. Sufficiency/Gate** | Path đã xác minh + evidence | Cho phép trả lời hoặc fail reason | Không chấp nhận generic path ngoài plan |

Sự không chắc chắn nằm chủ yếu ở **Planner** và **EntityLinker**. Sau khi bind
thành công, Executor và generation gate chạy deterministic, fail-closed trên
graph hiện có. Điều này không có nghĩa graph luôn đầy đủ hoặc plan luôn đúng ý
pháp lý; hai rủi ro đó được đo riêng ở Phần 5–6.

---

## Phần 3 — Luồng chạy đầy đủ (kèm ví dụ)

Dùng case `multi_hop_02` ở Phần 1. Năm chặng:

### Chặng 1 — AI viết "đơn hàng ràng buộc"

AI đọc câu hỏi và trả về một cấu trúc (KHÔNG phải đáp án, KHÔNG có ID node):

```jsonc
{
  "anchor": {
    "text": "Khoản 3 Điều 145",
    "expected_label": "Clause"
  },
  "steps": [
    {
      "relation": "REFERS_TO",
      "direction": "outgoing",
      "next_label": "Clause"
    },
    {
      "relation": "REFERS_TO",
      "direction": "outgoing",
      "next_label": "Clause"
    }
  ]
}
// Đích là Clause ở cuối chuỗi hai lần dẫn chiếu.
```

Đọc như tiếng Việt: *“Bắt đầu từ Khoản 3 Điều 145; đi theo dẫn chiếu tới một
Khoản; sau đó tiếp tục theo dẫn chiếu tới một Khoản khác.”*

### Chặng 2 — Bộ dò tên tìm điều luật thật

Bộ dò tên nhận cụm cấu trúc **“Khoản 3 Điều 145”**, cộng với document scope của
query/corpus, rồi resolve sang node thật:

```jsonc
candidates = [
  {
    "node_id": "ldn_2020_art145_cl3",
    "resolution": "unique_structural_match"
  }
]
```

Nếu document scope không xác định hoặc có nhiều node cùng khớp, EntityLinker trả
`AMBIGUOUS_ANCHOR` thay vì đoán.

Chi tiết Bộ dò tên ở [Phần 3.6](#36--bộ-dò-tên-entitylinker--chi-tiết).

### Chặng 3 — Máy dò đường trên Neo4j

Giờ có ID thật, máy dò theo đúng đơn hàng:

    Plan yêu cầu:
      Clause -> REFERS_TO -> Clause -> REFERS_TO -> Clause

    Neo4j trả về:
      ldn_2020_art145_cl3
        -> REFERS_TO -> ldn_2020_art145_cl2
        -> REFERS_TO -> ldn_2020_art145_cl1

    Executor kiểm:
      đúng anchor, đúng thứ tự, đúng chiều, đúng label, đúng thời điểm

### Chặng 4 — Kiểm tra "đủ để trả lời chưa"

Chỉ đường **đã xác minh** (đúng đơn hàng + trích dẫn được điều luật thật) mới được đi tiếp. Nếu đường tìm được không khớp đơn, hoặc không trích dẫn được → coi như chưa đủ.

### Chặng 5 — Sinh câu trả lời

AI viết câu trả lời chỉ từ nội dung của ba Khoản trên và trích dẫn các canonical
unit IDs tương ứng. Nó không được viện dẫn node hoặc path nằm ngoài context đã
được gate chấp nhận.

### Nếu bất kỳ chặng nào hỏng

Hệ thống **từ chối trung thực + báo rõ lý do** (mã lý do), không bịa. Bảng mã lý do ở [Phần 6.3](#63--đọc-log-biết-hỏng-ở-đâu).

### 3.6. Bộ dò tên (EntityLinker) — chi tiết

Đây là chỗ dễ hiểu lầm nhất, nên tách riêng.

**Nó nhận gì?** Một anchor mention cùng scope cần thiết để resolve, ví dụ
`“Khoản 3 Điều 145”` trong Luật Doanh nghiệp 2020; không phải toàn bộ plan.

**Nó có phải AI không?** Phần lớn **KHÔNG** — nó là *tra cứu / tìm kiếm*, không phải AI sinh chữ. Hai cơ chế:

1. **Tham chiếu cấu trúc** (thuần logic): nếu cụm chữ là `“Điều 12”`,
   `“Khoản 2 Điều 5”` thì parse số và tra canonical hierarchy. Chỉ resolve khi
   document scope và hierarchy cho đúng một kết quả.
2. **Khái niệm mơ hồ** (tìm kiếm): nếu là `“vốn điều lệ”` thì dùng semantic
   search + full-text search, trả về nhiều candidate có score.

**Vì sao tách khỏi AI?** An toàn: nếu để AI tự nói ID, nó **có thể bịa** một "Điều 99" không tồn tại. Nên **AI chỉ được nói chữ, chỉ Bộ dò tên (tìm trên graph thật) mới được tạo ID** — không thể trả về điều luật không có thật.

**Nó không chọn bừa:** structural reference phải resolve duy nhất; semantic
mention phải vượt ngưỡng và margin đã calibration. Nếu không đạt, trả
`UNBOUND_ANCHOR` hoặc `AMBIGUOUS_ANCHOR`. Việc thử nhiều candidate phải có
budget cố định và không được biến “có path” thành bằng chứng rằng candidate đó
đúng ý query.

> **Đây là rủi ro lớn nhất của cả giải pháp:** nếu Bộ dò tên neo sai điều luật ngay từ đầu, mọi bước sau đều sai. Vì vậy phải **đo độ chính xác của nó riêng, sớm** (Phần 6).

---

## Phần 4 — Cái đã có sẵn vs cái phải xây

Giải pháp **không xây từ số 0**. Phần khó về an toàn đã có; chỉ thiếu phần "vạch đường".

**Đã có (tái sử dụng):**
- Kiểm tra một đường đi có đúng hình dạng không (`graph.py`).
- Kiểm tra hiệu lực thời gian trên từng node/cạnh.
- Chống bịa trích dẫn (grounding), Neo4j, runtime truy vấn.
- "Người kiểm tra đủ" (`sufficiency.py`) — nhưng đang thiếu đầu vào.

**Phải xây mới:**

```
AI planner  →  Bộ dò tên  →  Máy dò đường  →  Kết quả có kiểm chứng  →  nối vào phần sinh câu trả lời
```

> Không phải "nối thêm một field", mà là lắp phần còn thiếu vào bộ khung đã tốt.

---

## Phần 5 — Phạm vi (nói thẳng nó làm và KHÔNG làm gì)

### 5.1. Chỉ ở read path — không đụng extraction

```
XÂY GRAPH (extraction)  — GIẢI PHÁP KHÔNG ĐỤNG TỚI
  crawl → parse → LLM trích xuất → validate → ghi Neo4j

TRẢ LỜI (read path)     — GIẢI PHÁP Ở ĐÂY
  câu hỏi → AI planner → Bộ dò tên → máy dò đường → trả lời
```

Hai lời gọi LLM **khác nhau**: LLM lúc trích xuất (ghi vào graph) ≠ LLM planner (lúc hỏi, chỉ sinh đơn hàng, không ghi gì).

### 5.2. Ba mức đảm bảo — đừng nhầm lẫn

| Mức | Nghĩa | Trạng thái |
|---|---|---|
| 1. Đường hợp lệ về cấu trúc/thời gian | cạnh nối đúng, còn hiệu lực | ✅ Làm được |
| 2. Đường đúng ý câu hỏi | khớp anchor/đích/thứ tự quan hệ | ⚠️ Đây là phần giải pháp xây |
| 3. Kết luận pháp lý đúng | evidence thật sự suy ra được claim | ❌ **Không** chứng minh; chỉ chặn bịa |

> Khi nói "đảm bảo đúng ~100%" thì **chỉ là mức 1**, không phải tính đúng pháp lý.

### 5.3. Những gì giải pháp KHÔNG giải quyết

- **Hiểu sai câu hỏi nhưng vẫn hợp lệ** (wrong-but-valid): AI có thể vạch đơn hàng đúng luật nhưng sai ý → phải **đo riêng**, hệ thống không tự bắt được.
- **Graph thiếu cạnh / trích xuất sai:** đây là lỗi khâu tạo graph, không phải read path (xem Phần 6).
- **Trong bản đầu (v1) chưa làm:** câu hỏi phân nhánh, ràng buộc "mềm", nhiều phương án, hỏi lại người dùng, chuỗi sửa đổi văn bản.

---

## Phần 6 — Cách kiểm chứng (làm theo thứ tự này)

### 6.1. TRƯỚC TIÊN: kiểm tra dữ liệu (bắt buộc, rẻ)

Toàn bộ giải pháp giả định graph **thật sự chứa** các chuỗi nhiều bước. Trước khi code, chạy probe nửa ngày trên Neo4j:

1. Đếm có bao nhiêu đường 2–3 bước (`REFERS_TO`/`DEFINES`/`GUIDES`…) thực tồn tại.
2. Lấy ~10 câu multi-hop, tự tay kiểm gold path có trong graph không.

**Diễn giải:**
- **Có đủ đường** → tiến hành xây (mục 6.2).
- **Thưa / không có** → **vấn đề thật nằm ở khâu tạo graph (extraction), KHÔNG phải ở read-path planner.** Máy dò đường có tốt đến đâu cũng không tìm được đường không tồn tại → xây planner lúc này là **giải sai bài** (chỉ làm cho câu từ chối "có lý do đẹp hơn"). Ưu tiên đúng: cải thiện độ dày/độ chính xác của quan hệ trong extraction, **hoặc** thu hẹp tuyên bố xuống đúng những gì graph hiện có (ví dụ chỉ single-hop).

### 6.2. Chứng minh trước, xây sau (hai cổng)

```
Cổng QG-0:  Đưa "đơn hàng vàng" (viết tay) cho máy dò đường.
            → Nếu máy dò chạy đúng khi đơn hoàn hảo (100% ca gold) → kiến trúc ổn, đi tiếp.
            → Nếu không đạt → DỪNG, khỏi tốn công xây AI planner.

Cổng QG-1:  Mới để AI planner tự viết đơn hàng, so với bản làm bằng luật cứng.
            → Đánh giá trên tập tài liệu tách riêng (leave-one-document-out).
```

Chiến lược này **cô lập rủi ro**: nếu hỏng ở QG-0 thì biết ngay là do máy dò/dữ liệu, chưa dính tới AI.

### 6.3. Đọc log biết hỏng ở đâu

| Mã lý do | Nghĩa | Hỏng ở chặng | Sửa ở đâu |
|---|---|---|---|
| `INVALID_PLAN` | AI ra đơn sai (quan hệ lạ, sai chiều, sai số bước) | Planner | prompt/schema |
| `UNBOUND_ANCHOR` | Không tìm ra điều luật cho cụm chữ | Bộ dò tên | index/tìm kiếm |
| `AMBIGUOUS_ANCHOR` | Nhiều ứng viên ngang điểm | Bộ dò tên | ngưỡng / hỏi lại |
| `NO_PATH` | Neo đúng nhưng graph không có đường | **Dữ liệu** | thường là graph thiếu cạnh (§6.1) |
| `TEMPORAL_REJECTED` | Có đường nhưng hết hiệu lực | Máy dò | đúng thiết kế |
| `EVIDENCE_UNLIFTABLE` | Tới đích nhưng không trích dẫn được | Lift evidence | đích là node ngữ nghĩa thiếu Điều/Khoản kề |

> Nhiều câu ra `NO_PATH` → **đừng sửa planner**, đó là dấu hiệu graph thiếu dữ liệu (quay lại §6.1).

---

## Phần 7 — Đặc tả cho người triển khai

Phần này dành cho người code. Người đọc để hiểu ý tưởng có thể dừng ở Phần 6.

### 7.1. Các kiểu dữ liệu (DTO)

```python
# Tầng 1 — AI sinh. KHÔNG node_id, KHÔNG số bước tự đoán, KHÔNG nguồn thời gian riêng.
class UnlinkedSemanticPlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    anchor: AnchorMention
    steps: tuple[PathStepConstraint, ...]        # exact-linear, 2..3 bước

    @model_validator(mode="after")
    def _check(self):
        if not (MIN_PLAN_DEPTH <= len(self.steps) <= MAX_PLAN_DEPTH):   # 2..3
            raise ValueError("depth out of bound")
        for s in self.steps[:-1]:                                       # bước giữa
            if s.next_label not in QUERY_TRAVERSAL_LABELS:
                raise ValueError("intermediate step has unsupported label")
        if self.steps[-1].next_label not in QUERY_TARGET_LABELS:
            raise ValueError("final step has unsupported target label")
        return self

    @property
    def target_label(self) -> str:               # đích = next_label của bước cuối
        return self.steps[-1].next_label

class AnchorMention(BaseModel):
    text: str
    expected_label: AnchorLabel | None = None    # AI gợi ý; Bộ dò tên mới quyết

class PathStepConstraint(BaseModel):
    relation: QueryPlannableRelation
    direction: Literal["outgoing", "incoming"]   # exact
    next_label: TraversalLabel | TargetLabel

# Bộ dò tên sinh — node_id chỉ xuất hiện ở đây
class BoundSemanticPlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    unlinked: UnlinkedSemanticPlan
    bound_anchor: BoundAnchor                     # mention → candidates(node_id, score)

# Máy dò đường sinh — kết quả có kiểm chứng
class PlanExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    plan_fingerprint: str
    satisfied_path_fingerprints: tuple[str, ...]  # cổng membership cho sufficiency
    bound_anchor_ids: tuple[str, ...]
    target_ids: tuple[str, ...]
    execution_status: Literal["satisfied", "failed"]
    reason_code: PlanReasonCode                   # enum đóng (bảng §6.3)
    message: str | None = None
    derived_reasoning_requirement: GraphReasoningRequirement | None   # artifact tương thích
```

### 7.2. Nhãn được phép — tách theo VAI TRÒ, chỉ dùng nhãn "chạy được"

Chỉ dùng nhãn/quan hệ **thật sự truy vấn được**, không phải toàn ontology (tránh AI sinh đơn hợp lệ nhưng không chạy được):

```python
QUERY_ANCHOR_LABELS    = frozenset({"Article", "Clause"})            # cần có index để tìm
QUERY_TRAVERSAL_LABELS = frozenset(PHASE1_PERSISTED_LABELS)          # node giữa
QUERY_TARGET_LABELS    = DIRECT_CITABLE_TARGETS | SEMANTIC_LIFTABLE_TARGETS
QUERY_PLANNABLE_RELATIONS = frozenset(PHASE1_RELATION_ENUM)          # đã trừ quan hệ chưa traverse được

DIRECT_CITABLE_TARGETS    = frozenset({"Article", "Clause", "Point"})
SEMANTIC_LIFTABLE_TARGETS = frozenset({"LegalConcept", "LegalSubject", "LegalAction"})
# Loại khỏi v1: Document, Chapter, Issuer (không có cách trích dẫn evidence)
```

### 7.3. Kiểm quan hệ đúng CHIỀU (không dùng validator lúc ghi)

Validator lúc ghi (`validators.py`) đòi các thuộc tính chỉ có lúc lưu (confidence, model…) → **không dùng được lúc lập kế hoạch**. Cần helper chỉ kiểm cấu trúc:

```python
def validate_directed_step(current_label, relation, direction, next_label):
    if direction == "outgoing":
        return validate_relation_pattern(current_label, relation, next_label)
    else:  # incoming: cạnh canonical là next -[REL]-> current
        return validate_relation_pattern(next_label, relation, current_label)
```

### 7.4. Điểm nối then chốt — chống "đường lạ lọt cổng"

- **Path fingerprint** (định danh đường ổn định) đặt ở tầng
  `retrieval/shared`, dựng từ canonical node IDs, loại quan hệ và chiều cạnh.
  Fingerprint không dùng mutable provenance/metadata như confidence, model hoặc
  created_at. Generation dùng lại cùng fingerprint, không tự định danh lần hai.
- Với câu multi-hop có kế hoạch: `sufficiency` phải kiểm **đường tìm được có nằm trong `satisfied_path_fingerprints` không TRƯỚC**, rồi mới áp điều kiện cũ. Nếu không, một đường chung chung không đúng kế hoạch có thể lọt cổng.
- `GraphReasoningRequirement` chỉ là **artifact tương thích** cho phần kiểm cũ; ngữ nghĩa thật (anchor/đích/thứ tự) nằm ở `PlanExecutionResult`.

### 7.5. Trích dẫn cho đích ngữ nghĩa

Node ngữ nghĩa (LegalConcept…) **không tự trích dẫn được** (chỉ Article/Clause/Point mới trích dẫn được). Nên đích ngữ nghĩa chỉ hợp lệ khi đường đi có **Article/Clause kề** làm chỗ dựa trích dẫn (ví dụ `Article -[DEFINES]-> LegalConcept` → trích dẫn Article nguồn).

### 7.6. Ranh giới khác

- **Thời gian:** dùng lại `TemporalQuery` sẵn có làm nguồn duy nhất; planner **không** tạo nguồn thời gian song song.
- **Bộ dò tên:** định nghĩa `StructuralAnchorResolverPort` thuộc retrieval; **không** import registry của extraction (giữ đúng chiều phụ thuộc).
- **Sync/async:** planner là lời gọi LLM async, retrieval đang đồng bộ → phải có adapter timeout/hủy rõ ràng, không gọi async tùy tiện trong luồng đồng bộ.

---

## Phần 8 — Kết luận

Giải pháp lấp đúng chỗ khiến câu hỏi multi-hop bị từ chối:

1. Planner chuyển câu hỏi thành một pattern quan hệ có thứ tự.
2. EntityLinker gắn anchor vào canonical node có thật.
3. Executor chỉ chạy đúng pattern đó trên Neo4j.
4. Sufficiency chỉ mở generation gate cho path đã thực sự thỏa plan.
5. Bất kỳ bước nào thất bại đều trả reason code và không sinh câu trả lời.

Nói gọn: **LLM mô tả cần tìm đường gì; code tìm và kiểm đường thật; answer
generation chỉ được dùng evidence nằm trên đường đã kiểm.**

Điều kiện tiên quyết: **graph phải có dữ liệu multi-hop** (kiểm ở §6.1). Rủi ro lớn nhất là **Bộ dò tên**, không phải AI planner. Chiến lược đúng: **kiểm dữ liệu → chứng minh máy dò đường (QG-0) → mới xây AI planner (QG-1)**, và giữ tuyên bố đúng phạm vi *multi-hop tuyến tính, đảm bảo mức 1*.
