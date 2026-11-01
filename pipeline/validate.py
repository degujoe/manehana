#!/usr/bin/env python3
"""Check question files without writing anything (safe to run any time, offline).

  python pipeline/validate.py              # every question
  python pipeline/validate.py seoul_gu tteok

Checks: required fields, at least 25 answers, gem and anchors are answers,
a gem_note exists, every name/alias belongs to exactly one answer, nothing in
reject: is an answer, no duplicate answers. Exit code 1 if anything is wrong.
"""
import sys

import common


def key(x):
    return "".join(str(x).split()).lower()


def check(p):
    errs = []
    names = [a["name"] for a in p["answers"]]
    if len(names) < 25:
        errs.append(f"only {len(names)} answers (need at least 25)")
    if len(set(names)) != len(names):
        errs.append("duplicate answers: " + ", ".join(sorted({n for n in names if names.count(n) > 1})))
    if p["gem"] not in names:
        errs.append(f"gem '{p['gem']}' is not an answer")
    if not p.get("gem_note"):
        errs.append("missing gem_note (one sentence about the gem, shown to players)")
    for pair in p["anchors"]:
        for x in pair:
            if str(x) not in names:
                errs.append(f"anchor '{x}' is not an answer")
    if not 3 <= len(p["anchors"]) <= 5:
        errs.append(f"{len(p['anchors'])} anchors (want 3-5)")
    owner = {}
    for a in p["answers"]:
        for form in [a["name"]] + a["aliases"]:
            k = key(form)
            if k in owner and owner[k] != a["name"]:
                errs.append(f"'{form}' is listed for both '{owner[k]}' and '{a['name']}'")
            owner.setdefault(k, a["name"])
        if a.get("tier") is not None and not a.get("note"):
            errs.append(f"'{a['name']}' has tier: but no note:")
    for x in p["reject"]:
        if key(x) in owner:
            errs.append(f"reject '{x}' is also an answer/alias of '{owner[key(x)]}'")
    if not p.get("sources"):
        errs.append("no sources:")
    return errs


def main():
    want = sys.argv[1:]
    bad = 0
    for p in common.load_prompts():
        if want and p["id"] not in want:
            continue
        errs = check(p)
        print(f"{'❌' if errs else '✅'} {p['id']} ({p['label']}, {len(p['answers'])} answers, {p['status']})")
        for e in errs:
            print(f"   - {e}")
        bad += bool(errs)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
