#!/usr/bin/env python3
"""Search tree for likely hardcoded secrets and print matches with file:line."""
import re, sys
from pathlib import Path

PATTERNS = [
    r"API_KEY\s*=\s*['\"][A-Za-z0-9_\-]{16,}['\"]",
    r"SECRET(_KEY)?\s*=\s*['\"][^'\"]{10,}['\"]",
    r"PASSWORD\s*=\s*['\"][^'\"]{6,}['\"]",
    r"SCHWAB_BEARER_TOKEN\s*=\s*['\"][^'\"]+['\"]",
]
def main(root: str):
    rootp = Path(root)
    for p in rootp.rglob("*.py"):
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pat in PATTERNS:
            for m in re.finditer(pat, txt):
                line = txt[:m.start()].count("\n") + 1
                print(f"{p}:{line}: matched {pat}")
if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv)>1 else ".")
