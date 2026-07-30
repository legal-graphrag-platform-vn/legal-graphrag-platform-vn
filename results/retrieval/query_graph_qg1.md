# QG-1 query planning evaluation

> Phạm vi: development case study. Không phải kết quả official.

Gold manual planner chỉ là upper bound để cô lập executor; không phải baseline cạnh tranh.

- Threshold status: `failed`
- Dataset SHA-256: `7c14744c582288f981f3cb16b0552b60f5297b1e3de5a07774d024c783496ba1`
- Graph snapshot SHA-256: `294cf005d4d5926d5d09c9388236ff23d92cd6b845eeaef89a4d263f6280e291`
- Planner: `gemini:gemini-3.1-flash-lite`
- Prompt fingerprint: `415ed9c2e85ee42a5fed462cd3c3bbed3f1d8d02c8843fee8ee741f6981affa4`

| Profile | Role | Schema valid | Exact plan | Anchor | Target | Exact path | Extra path | Graph hit |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| generic_retrieval | reference | n/a | n/a | n/a | n/a | 0.000 | 1.000 | 0.000 |
| rule_based_planner | baseline | 1.000 | 1.000 | 0.667 | 0.333 | 0.333 | 0.000 | 0.333 |
| gold_manual_upper_bound | upper_bound | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| llm_planner | candidate | 0.667 | 0.667 | 0.333 | 0.000 | 0.000 | 0.000 | 0.000 |

## LLM target-linker diagnostic

| Query | Target mention | Status | Gold rank | Top score | Top-2 margin | Candidates |
|---|---|---|---:|---:|---:|---|
| multi_hop_01 | khoản xác định tên gây nhầm lẫn tại Điều 41 | ambiguous | 1 | 0.063797 | 0.000770 | 1:ldn_2020_art41_cl2(0.063797); 2:ldn_2020_art38_cl1(0.063027); 3:ldn_2020_art41_cl3(0.047907); 4:ldn_2020_art41_cl1(0.047403); 5:ldn_2020_art38_cl3(0.045730); 6:ldn_2020_art37_cl5(0.045235); 7:ldn_2020_art16_cl4(0.014493); 8:ldn_2020_art16_cl5(0.014286) |
| multi_hop_04 | trình tự chào bán phần vốn góp | unbound | n/a | 0.047073 | 0.001093 | 1:ldn_2020_art123_cl1(0.047073); 2:ldn_2020_art124_cl1(0.045980); 3:ldn_2020_art124_cl4(0.045760); 4:ldn_2020_art112_cl3(0.031025); 5:ldn_2020_art126_cl2(0.029877) |

Corpus hiện chỉ gồm các case đã review trong `ldn_2020`; không claim khả năng generalize hoặc leave-one-document-out.
