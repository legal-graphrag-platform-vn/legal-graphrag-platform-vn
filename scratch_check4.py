import os
import json
from pathlib import Path

processed_dir = Path("data/processed")
manifest_path = Path("data/manifest_luatdoanhnghiep.json")

with open(manifest_path, 'r') as f:
    manifest = json.load(f)
    docs = manifest.get('documents', [])
    doc_codes = [d['raw_doc_code'] for d in docs]

for code in doc_codes:
    doc_dir = processed_dir / code
    if doc_dir.exists() and not (doc_dir / "article_extractions.jsonl").exists() and (doc_dir / "hierarchy.json").exists():
        print(f"Failed doc: {code}")
        os.system(f"ls -la {doc_dir}")
        break
