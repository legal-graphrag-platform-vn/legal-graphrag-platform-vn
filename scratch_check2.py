import os
from pathlib import Path

processed_dir = Path("data/processed")
missing_parsed = []
for d in processed_dir.iterdir():
    if d.is_dir() and not (d / "parsed.json").exists():
        missing_parsed.append(d)

if missing_parsed:
    d = missing_parsed[0]
    print(d)
    os.system(f"ls -la {d}")
