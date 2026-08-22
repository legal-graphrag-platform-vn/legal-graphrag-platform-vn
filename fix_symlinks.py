import os
from pathlib import Path

processed_dir = Path("data/processed")
symlink_targets = {
    "current_extraction": lambda content: content.startswith("artifact_sets/"),
    "accepted.jsonl": lambda content: content.startswith("current_extraction/"),
    "entity_index.json": lambda content: content.startswith("current_extraction/"),
    "extract.jsonl": lambda content: content.startswith("current_extraction/"),
    "rejected.jsonl": lambda content: content.startswith("current_extraction/"),
    "review.jsonl": lambda content: content.startswith("current_extraction/"),
    "prettier_extract.json": lambda content: content.startswith("current_extraction/"),
    "extraction_run.json": lambda content: content.startswith("current_extraction/"),
}

fixed_count = 0

for doc_dir in processed_dir.iterdir():
    if not doc_dir.is_dir():
        continue
    
    for fname, condition in symlink_targets.items():
        fpath = doc_dir / fname
        if fpath.exists() and fpath.is_file() and not fpath.is_symlink():
            try:
                # Read content
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                
                # Check if it's a broken symlink string
                if condition(content) and len(content) < 200:
                    # Remove the file
                    fpath.unlink()
                    # Create symlink
                    os.symlink(content, fpath)
                    fixed_count += 1
            except Exception as e:
                print(f"Error fixing {fpath}: {e}")

print(f"Fixed {fixed_count} broken symlinks.")
