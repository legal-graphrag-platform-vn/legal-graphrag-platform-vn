# QG-0 — Manual gold-plan execution

> Captured: 2026-07-23T14:23:36.205960+00:00
>
> Result: **PASSED — Task 6 may begin**
>
> Scope: development pilot, `ldn_2020`, ontology v1.6.0

## Gate result

Ba exact-linear V1 cases đều resolve structural anchor về đúng canonical ID và
trả đúng một denotation khớp toàn bộ gold node/relation sequence. Không có path
false positive. QG-0 chỉ đo executor với target endpoint được bind thủ công;
không đo semantic target linker hoặc planner LLM.

| Case | Anchor | Gold/returned path | Latency | Result |
|---|---|---|---:|---|
| `multi_hop_01` | `art38_cl1` | `art38_cl1 -REFERS_TO-> art41 -CONTAINS-> art41_cl2` | 13.858 ms | Pass |
| `multi_hop_02` | `art145_cl3` | `art145_cl3 -REFERS_TO-> art145_cl2 -REFERS_TO-> art145_cl1` | 21.072 ms | Pass |
| `multi_hop_04` | `art68_cl2` | `art68_cl2 -REFERS_TO-> art52 -CONTAINS-> art52_cl1` | 13.929 ms | Pass |

## Negative checks

- Đảo direction của step đầu: `NO_PATH`.
- Dùng target không tồn tại để mô phỏng thiếu edge: `NO_PATH`.
- Answer-provider calls sau failure: `0` — QG-0 runner không có dependency tới
  answer provider.
- Legacy relation aliases: config contract reject trước execution.

## Pinned evidence

| Field | Value |
|---|---|
| Gold config SHA-256 | `7c14744c582288f981f3cb16b0552b60f5297b1e3de5a07774d024c783496ba1` |
| Graph preflight projection SHA-256 | `294cf005d4d5926d5d09c9388236ff23d92cd6b845eeaef89a4d263f6280e291` |
| Neo4j | Community 5.26.28, `bolt://127.0.0.1:7688` |
| Document scope | `ldn_2020` |

`multi_hop_03` là direct atomic one-hop reference và `multi_hop_05` là branching;
cả hai nằm ngoài exact-linear V1 nên không được tính vào mẫu số QG-0.

Kết quả này là development case study trên một document, không phải official
cross-document evaluation hoặc bằng chứng generalization.
