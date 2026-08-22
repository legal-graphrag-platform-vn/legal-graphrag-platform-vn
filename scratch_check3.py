import os
import json
from pathlib import Path

processed_dir = Path("data/processed")
manifest_path = Path("data/manifest_luatdoanhnghiep.json")

with open(manifest_path, 'r') as f:
    manifest = json.load(f)
    docs = manifest.get('documents', [])
    doc_codes = [d['raw_doc_code'] for d in docs]

total = len(doc_codes)
completed = 0
failed_or_missing = 0
reasons = {}

for code in doc_codes:
    doc_dir = processed_dir / code
    if not doc_dir.exists():
        failed_or_missing += 1
        reasons["missing_dir"] = reasons.get("missing_dir", 0) + 1
        continue
    
    if (doc_dir / "error.log").exists():
        failed_or_missing += 1
        reasons["has_error_log"] = reasons.get("has_error_log", 0) + 1
    elif (doc_dir / "article_extractions.jsonl").exists():
        completed += 1
    else:
        # Check hierarchy.json
        if (doc_dir / "hierarchy.json").exists():
            # If hierarchy exists but article_extractions.jsonl is missing, it failed extraction
            failed_or_missing += 1
            reasons["failed_extraction"] = reasons.get("failed_extraction", 0) + 1
        else:
            failed_or_missing += 1
            reasons["missing_hierarchy"] = reasons.get("missing_hierarchy", 0) + 1

print(f"Total in manifest: {total}")
print(f"Completed: {completed}")
print(f"Failed/Missing: {failed_or_missing}")
print(f"Reasons: {reasons}")
