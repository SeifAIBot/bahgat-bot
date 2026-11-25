"""Load persona.yaml + examples.md at startup (config-driven, not hardcoded).
If the files are missing, fall back to the built-in defaults in brain/prompt.py.
"""
import re
import yaml
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def load_persona():
    p = ROOT / "config" / "persona.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}

def load_examples(max_n=8):
    """Parse persona/bahgat/examples.md pair format: one "User: ... / Bahgat: ..."
    pair per blank-line-separated block. Returns a list of strings, each
    "User: <...>\\nBahgat: <...>" (pairs kept together)."""
    p = ROOT / "persona" / "bahgat" / "examples.md"
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if len(lines) >= 2 and lines[0].startswith("User:") and any(
            l.startswith("Bahgat:") for l in lines
        ):
            out.append("\n".join(lines))
    return out[:max_n]
