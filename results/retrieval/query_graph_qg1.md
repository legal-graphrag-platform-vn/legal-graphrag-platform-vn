# QG-1 query planning evaluation

> Phạm vi: development case study. Không phải kết quả official.

Gold manual planner chỉ là upper bound để cô lập executor; không phải baseline cạnh tranh.

- Threshold status: `failed`
- Dataset SHA-256: `7c14744c582288f981f3cb16b0552b60f5297b1e3de5a07774d024c783496ba1`
- Graph snapshot SHA-256: `multi_doc_test_corpus_v1`
- Planner: `gemini:gemini-3.1-flash-lite`
- Prompt fingerprint: `95484bd8c81163c86e14cbf12e4ef53ef02875390b1ae7d942785b31bb1bcfea`

| Profile | Role | Schema valid | Exact plan | Anchor | Target | Exact path | Extra path | Graph hit |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| generic_retrieval | reference | n/a | n/a | n/a | n/a | 0.000 | 1.000 | 0.000 |
| rule_based_planner | baseline | 1.000 | 1.000 | 0.667 | 0.333 | 0.333 | 0.000 | 0.333 |
| gold_manual_upper_bound | upper_bound | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| llm_planner | candidate | 0.667 | 0.667 | 0.333 | 0.000 | 0.000 | 0.000 | 0.000 |

## LLM target-linker diagnostic

| Query | Target mention | Status | Gold rank | Top score | Top-2 margin | Candidates |
|---|---|---|---:|---:|---:|---|
| multi_hop_01 | khoản quy định tên gây nhầm lẫn tại Điều 41 | ambiguous | 1 | 0.064037 | 0.000521 | 1:ldn_2020_art41_cl2(0.064037); 2:ldn_2020_art38_cl1(0.063516); 3:ldn_2020_art41_cl1(0.047891); 4:ldn_2020_art38_cl3(0.046183); 5:ldn_2020_art38_cl2(0.045964); 6:ldn_2020_art37_cl5(0.045688); 7:ldn_2020_art16_cl5(0.014493); 8:ldn_2020_art71_cl3(0.014286) |
| multi_hop_04 | khoản quy định trình tự chào bán phần vốn góp tại Điều 52 | unbound | 1 | 0.048172 | 0.000264 | 1:ldn_2020_art52_cl1(0.048172); 2:ldn_2020_art52_cl2(0.047907); 3:ldn_2020_art52_cl3(0.046484); 4:ldn_2020_art112_cl3(0.029857); 5:ldn_2020_art112_cl2(0.029631); 6:ldn_2020_art51_cl3(0.028778); 7:ldn_2020_art53_cl4(0.015873); 8:ldn_2020_art23_cl5(0.015625) |

Corpus hiện chỉ gồm các case đã review trong `ldn_2020`; không claim khả năng generalize hoặc leave-one-document-out.
