"""Plugin registry — one interface, loaded from config/plugins.yaml.
Each plugin: can_handle(text, ctx) -> bool, async handle(ctx) -> dict.
"""
import yaml
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def load_enabled():
    p = ROOT / "config" / "plugins.yaml"
    if not p.exists():
        return []
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return cfg.get("plugins", [])
