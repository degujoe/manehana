"""Shared paths and loading for the 만에 하나 data pipeline."""
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "data" / "prompts"
SIGNALS_DIR = ROOT / "data" / "signals"
GAME_JSON = ROOT / "data" / "game.json"
GAME_JS = ROOT / "data" / "game.js"
REPORT = ROOT / "data" / "report.md"
SUMMARY = ROOT / "data" / "summary.md"
HAND_TIERS = ROOT / "data" / "hand_tiers.json"

TIER_NAMES = {1: "멸치", 2: "대왕오징어", 3: "초롱아귀", 4: "덤보문어", 5: "옆새우 (만에 하나)"}

REQUIRED = ["id", "label", "question", "hint", "gem", "wiki_titles", "context", "answers"]


def load_prompts():
    prompts = []
    for path in sorted(PROMPTS_DIR.glob("*.yaml")):
        p = yaml.safe_load(path.read_text("utf8"))
        missing = [k for k in REQUIRED if k not in p]
        if missing:
            raise SystemExit(f"{path.name}: missing {', '.join(missing)}")
        if p["id"] != path.stem:
            raise SystemExit(f"{path.name}: id is '{p['id']}' but the file name says '{path.stem}'")
        p.setdefault("status", "live")
        p.setdefault("strip", [])
        p.setdefault("anchors", [])
        p.setdefault("use_wordfreq", False)
        for a in p["answers"]:
            a["name"] = str(a["name"])
            a["aliases"] = [str(x) for x in a.get("aliases", [])]
        prompts.append(p)
    return prompts
