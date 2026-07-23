# Query graph semantic linker calibration

> Ngày chạy: 2026-07-23  
> Scope: `pilot_development`, document `ldn_2020`  
> Embedding: `flag_embedding:BAAI/bge-m3:1024`  
> Fusion: deterministic hierarchy-aware RRF, `rrf_k=60`

## Cấu hình được chọn

| Role | Candidate budget | Minimum score | Minimum margin |
|---|---:|---:|---:|
| Anchor | 10 | 0.063 | 0.001 |
| Target | 10 | 0.063 | 0.001 |

Calibration quét score theo bước `0.001` trong `[0.001, 0.100]` và margin theo
bước `0.001` trong `[0.001, 0.020]`. Tiêu chí chọn theo thứ tự:

1. Không có false resolution.
2. Tối đa số endpoint resolve đúng.
3. Chọn score threshold thấp hơn, sau đó margin thấp hơn nếu vẫn hòa.

Không dùng graph path existence, target reachability hoặc executor result làm
ranking feature/tie-break. Path execution được báo riêng từ QG-0.

## Kết quả

| Metric | Anchor | Target | Path execution |
|---|---:|---:|---:|
| Case count | 3 | 3 | 3 |
| Correct exact endpoint | 1 | 2 | 3 |
| False resolution | 0 | 0 | 0 |
| Accuracy | 0.3333 | 0.6667 | 1.0000 |
| Resolved precision | 1.0000 | 1.0000 | 1.0000 |

Target mô tả việc chuyển nhượng/chào bán phần vốn góp resolve đúng
`ldn_2020_art52_cl1`. Hai case meeting/semantic còn lại bị từ chối thay vì bind
sai khi không vượt ngưỡng. Đây là calibration phát triển trên tập nhỏ, chưa phải
tuyên bố corpus-level accuracy.

## Reproduce

Artifact đầu vào được pin tại
`configs/evaluation/query_graph_linker_calibration.json`. Chạy:

```bash
uv run pytest -q src/retrieval/tests/test_semantic_endpoint_linker.py
```

Test calibration tái tính threshold từ candidate scores đã pin và kiểm anchor,
target, path execution accuracy là ba metric độc lập.
