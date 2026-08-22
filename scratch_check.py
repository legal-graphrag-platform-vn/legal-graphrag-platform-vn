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
    
    # check for extract.jsonl or similar indicator of success
    # assuming success if artifact_sets has at least one extract.jsonl OR if the doc has no articles
    # Actually, a better way is to check if it's considered completed by the pipeline.
    # The pipeline usually writes an error.log or similar if it fails.
    if (doc_dir / "error.log").exists():
        failed_or_missing += 1
        reasons["has_error_log"] = reasons.get("has_error_log", 0) + 1
    elif (doc_dir / "article_extractions.jsonl").exists():
        completed += 1
    else:
        # maybe no articles?
        # check if parsed.json exists
        if (doc_dir / "parsed.json").exists():
            with open(doc_dir / "parsed.json", 'r') as f:
                parsed = json.load(f)
                if not parsed.get('children'):
                    completed += 1
                else:
                    failed_or_missing += 1
                    reasons["missing_extractions"] = reasons.get("missing_extractions", 0) + 1
        else:
            failed_or_missing += 1
            reasons["missing_parsed"] = reasons.get("missing_parsed", 0) + 1

print(f"Total in manifest: {total}")
print(f"Completed: {completed}")
print(f"Failed/Missing: {failed_or_missing}")
print(f"Reasons: {reasons}")
