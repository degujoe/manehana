#!/usr/bin/env python3
"""Score every answer, assign tiers, run the accuracy checks and build the game data.

  python pipeline/build.py

Reads  data/prompts/*.yaml and data/signals/*.json
Writes data/game.json, data/game.js (loaded by index.html) and data/report.md

Exits with code 1 if any check fails, so a bad update can't be merged unnoticed.
No internet needed.

How a score is made
-------------------
Each signal is turned into a percentile *within its own question* (1.0 = the
most common answer, 0.0 = the rarest), so pageviews for kings and for fish
never have to be compared directly. The familiarity score is the weighted
average of the percentiles the answer has. Answers are then sorted and split
into tiers by the question's `cutoffs` (default: top 15% grey, next 25% blue,
next 30% red, rest purple). The gem is always gold.

Guard rails
-----------
* ceiling: if ANY signal puts an answer in the top 10% of its question, it can't
  go below blue, however the other signals score it.
* floor: if every signal (at least two) puts it in the bottom 25%, it can't be
  grey or blue.
* anchors: hand-checked pairs that must come out in order, or the build fails.
* gem: the gem must score at least red on the data ("too clever" check).
* overrides: a hand-set `tier:` needs a `note:` saying why.
"""
import json
import sys

import common

# Default weight of each signal. A question can override these with `weights:` in its file
# (everyday-word questions lean on mentions and word frequency, since nobody looks up
# 고등어 on Wikipedia but everyone knows it).
WEIGHTS = {"count": 3.0, "mentions": 2.0, "pageviews": 2.0, "wordfreq": 1.0, "sitelinks": 0.5}
DEFAULT_CUTOFFS = [0.15, 0.40, 0.70]
CEILING_PCT = 0.90
FLOOR_PCT = 0.25
DISAGREE = 0.60


def percentiles(values):
    """{name: value} -> {name: percentile 0..1}, ties share the average rank."""
    items = [(k, v) for k, v in values.items() if v is not None]
    n = len(items)
    if n == 0:
        return {}
    if n == 1:
        return {items[0][0]: 0.5}
    vals = sorted(v for _, v in items)
    out = {}
    for k, v in items:
        below = sum(1 for x in vals if x < v)
        equal = sum(1 for x in vals if x == v)
        out[k] = (below + (equal - 1) / 2) / (n - 1)
    return out


def usable_signals(prompt, sig):
    """Which raw numbers can be trusted for each answer."""
    answers = sig.get("answers", {})
    raw = {k: {} for k in WEIGHTS}
    cs = sig.get("count_source") or {}
    count_reliable = cs.get("matched", 0) >= 0.5 * max(1, cs.get("of", 1))
    for a in prompt["answers"]:
        r = answers.get(a["name"], {})
        st = r.get("status")
        if st == "ok" or st == "missing":
            raw["pageviews"][a["name"]] = r.get("pageviews")
            raw["sitelinks"][a["name"]] = r.get("sitelinks") if st == "ok" else None
        if prompt.get("use_wordfreq") and not r.get("wordfreq_homonym"):
            raw["wordfreq"][a["name"]] = r.get("wordfreq")
        raw["mentions"][a["name"]] = r.get("mentions")
        if prompt.get("count_source") and count_reliable:
            # answers missing from a well-matched census table are very rare
            raw["count"][a["name"]] = r.get("count") or 0
    return raw


def score_prompt(prompt, sig, previous):
    w = dict(WEIGHTS, **(prompt.get("weights") or {}))
    raw = usable_signals(prompt, sig)
    pct = {k: percentiles(v) for k, v in raw.items() if w.get(k, 0) > 0}
    rows = []
    for a in prompt["answers"]:
        name = a["name"]
        mine = {k: pct[k][name] for k in pct if name in pct[k]}
        fam = (sum(w[k] * v for k, v in mine.items()) / sum(w[k] for k in mine)) if mine else None
        rows.append({"name": name, "aliases": a["aliases"], "fam": fam, "pct": mine,
                     "raw": {k: raw[k].get(name) for k in WEIGHTS},
                     "sig": sig.get("answers", {}).get(name, {}),
                     "override": a.get("tier"), "note": a.get("note"),
                     "prev": previous.get(name)})

    cut = prompt.get("cutoffs", DEFAULT_CUTOFFS)
    known = sorted([r for r in rows if r["fam"] is not None], key=lambda r: -r["fam"])
    n = len(known)
    for i, r in enumerate(known):
        share = (i + 0.5) / n
        t = 1 if share < cut[0] else 2 if share < cut[1] else 3 if share < cut[2] else 4
        rule = ""
        top = max(r["pct"].values())
        if top >= CEILING_PCT and t > 2:
            t, rule = 2, "ceiling"
        if len(r["pct"]) >= 2 and top <= FLOOR_PCT and t < 3:
            t, rule = 3, "floor"
        r["computed"], r["rule"] = t, rule

    problems, warnings = [], []
    for r in rows:
        if r["fam"] is None:
            r["computed"], r["rule"] = None, "no data"
        if r["name"] == prompt["gem"]:
            r["tier"] = 5
        elif r["override"] is not None:
            if not r["note"]:
                problems.append(f"`{r['name']}` has `tier: {r['override']}` but no `note:` explaining why")
            r["tier"] = int(r["override"])
        elif r["computed"] is not None:
            r["tier"] = r["computed"]
        else:
            r["tier"] = r["prev"] if r["prev"] in (1, 2, 3, 4) else 3
            if r["sig"].get("status") != "check":
                warnings.append(f"`{r['name']}`: no usable data ({r['sig'].get('status', 'not collected')}); "
                                f"kept tier {r['tier']}. {r['sig'].get('note', '')}".strip())
        st = r["sig"].get("status")
        if st == "check":
            warnings.append(f"`{r['name']}`: article [{r['sig'].get('article')}] may be the wrong topic "
                            f"({r['sig'].get('note')}). Its pageviews were not used; pin the right title with `wiki:`")
        if len(r["pct"]) >= 2 and max(r["pct"].values()) - min(r["pct"].values()) >= DISAGREE:
            spread = ", ".join(f"{k} {v:.2f}" for k, v in r["pct"].items())
            warnings.append(f"`{r['name']}`: signals disagree ({spread})")

    # every name and alias must point to exactly one answer, and nothing rejected may be an answer
    def key(x):
        return "".join(str(x).split()).lower()
    owner = {}
    for a in prompt["answers"]:
        for form in [a["name"]] + a["aliases"]:
            k = key(form)
            if k in owner and owner[k] != a["name"]:
                problems.append(f"`{form}` is listed for both `{owner[k]}` and `{a['name']}`")
            owner.setdefault(k, a["name"])
    for x in prompt["reject"]:
        if key(x) in owner:
            problems.append(f"`{x}` is in `reject:` but is also an answer or alias of `{owner[key(x)]}`")

    by = {r["name"]: r for r in rows}
    gem = by.get(prompt["gem"])
    if not gem:
        problems.append(f"gem `{prompt['gem']}` is not one of the answers")
    elif gem["computed"] is not None and gem["computed"] < 3:
        problems.append(f"gem `{gem['name']}` scores as {common.TIER_NAMES[gem['computed']]} on the data: "
                        "too well known to be the gem (\"too clever\"). Pick a rarer gem.")

    anchors = []
    for pair in prompt["anchors"]:
        easy, hard = by.get(str(pair[0])), by.get(str(pair[1]))
        if not easy or not hard:
            problems.append(f"anchor {pair}: not both are answers")
            continue
        if easy["fam"] is None or hard["fam"] is None:
            ok, why = False, "no data to compare"
        elif easy["fam"] <= hard["fam"]:
            ok, why = False, f"{easy['name']} {easy['fam']:.2f} ≤ {hard['name']} {hard['fam']:.2f}"
        elif easy["tier"] > hard["tier"]:
            ok, why = False, f"{easy['name']} got a rarer tier than {hard['name']}"
        else:
            ok, why = True, f"{easy['fam']:.2f} > {hard['fam']:.2f}"
        anchors.append((pair, ok, why))
        if not ok:
            problems.append(f"anchor `{pair[0]}` > `{pair[1]}` failed: {why}")

    return rows, problems, warnings, anchors


def fmt_num(v):
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:.1f}"
    return f"{v:,}"


def report_section(prompt, sig, rows, problems, warnings, anchors):
    counts = {t: sum(1 for r in rows if r["tier"] == t) for t in range(1, 6)}
    status = "❌" if problems else ("⚠️" if warnings else "✅")
    L = [f"## {status} {prompt['label']} (`{prompt['id']}`){' — draft' if prompt['status'] != 'live' else ''}", ""]
    L.append(f"{len(rows)} answers · collected {sig.get('collected') or 'never'} · "
             + " · ".join(f"{common.TIER_NAMES[t]} {counts[t]}" for t in range(1, 6)))
    cs = sig.get("count_source")
    if cs:
        L.append(f"\nCounts from [{cs['page']}]: matched {cs['matched']} of {cs['of']} answers"
                 + ("" if cs["matched"] >= cs["of"] * 0.5 else " — too few, counts not used"))
    L.append("")
    if problems:
        L += ["**Must fix:**"] + [f"- {p}" for p in problems] + [""]
    ok = sum(1 for a in anchors if a[1])
    L.append(f"Anchors: {ok}/{len(anchors)} passed")
    L += [f"- {'✅' if a[1] else '❌'} {a[0][0]} > {a[0][1]} ({a[2]})" for a in anchors]
    L.append("")
    changed = [r for r in rows if r["prev"] is not None and r["prev"] != r["tier"]]
    if changed:
        L.append(f"<details><summary>Tier changes ({len(changed)})</summary>\n")
        L += [f"- {r['name']}: {common.TIER_NAMES.get(r['prev'], r['prev'])} → {common.TIER_NAMES[r['tier']]}"
              for r in changed]
        L += ["", "</details>", ""]
    if warnings:
        L.append(f"<details><summary>Needs a look ({len(warnings)})</summary>\n")
        L += [f"- {w}" for w in warnings] + ["", "</details>", ""]
    L.append("<details><summary>All answers</summary>\n")
    L.append("| answer | tier | score | pageviews (12 mo) | wiki mentions | languages | word freq | count | article |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: (-(r["fam"] if r["fam"] is not None else -1))):
        s = r["sig"]
        tier = common.TIER_NAMES[r["tier"]] + (f" ({r['rule']})" if r.get("rule") else "") \
            + (" (set by hand)" if r["override"] is not None and r["name"] != prompt["gem"] else "")
        art = s.get("article") or s.get("status", "")
        L.append(f"| {r['name']} | {tier} | {fmt_num(r['fam'] and round(r['fam'], 2))} | "
                 f"{fmt_num(s.get('pageviews'))} | {fmt_num(s.get('mentions'))} | {fmt_num(s.get('sitelinks'))} | "
                 f"{fmt_num(s.get('wordfreq'))}{'*' if s.get('wordfreq_homonym') else ''} | "
                 f"{fmt_num(s.get('count'))} | {art} |")
    L += ["", "</details>", ""]
    return "\n".join(L)


def main():
    prompts = common.load_prompts()
    previous = {}
    if common.GAME_JSON.exists():
        for p in json.loads(common.GAME_JSON.read_text("utf8"))["prompts"]:
            previous[p["id"]] = {a["name"]: a["tier"] for a in p["answers"]}
    elif common.HAND_TIERS.exists():
        previous = json.loads(common.HAND_TIERS.read_text("utf8"))

    game, sections, failed, total_warn, summary = [], [], [], 0, []
    for p in prompts:
        sp = common.SIGNALS_DIR / f"{p['id']}.json"
        sig = json.loads(sp.read_text("utf8")) if sp.exists() else {}
        rows, problems, warnings, anchors = score_prompt(p, sig, previous.get(p["id"], {}))
        sections.append(report_section(p, sig, rows, problems, warnings, anchors))
        mark = "❌" if problems else ("⚠️" if warnings else "✅")
        summary.append(f"- {mark} **{p['label']}** (`{p['id']}`): {len(rows)} answers, "
                       f"anchors {sum(1 for a in anchors if a[1])}/{len(anchors)}, {len(warnings)} to look at")
        summary += [f"  - must fix: {x}" for x in problems]
        total_warn += len(warnings)
        if problems:
            failed.append(p["id"])
        if p["status"] == "live":
            game.append({"id": p["id"], "label": p["label"], "q": p["question"], "hint": p["hint"],
                         "strip": p["strip"], "reject": p["reject"],
                         "answers": [{"name": r["name"], "aliases": r["aliases"], "tier": r["tier"]} for r in rows]})

    head = ["# 만에 하나 data report", "",
            f"{len(prompts)} questions ({len(game)} live) · "
            f"{sum(len(p['answers']) for p in prompts)} answers · "
            f"{'❌ ' + str(len(failed)) + ' with problems: ' + ', '.join(failed) if failed else '✅ all checks passed'}"
            f" · {total_warn} things to look at", "",
            "Generated by `pipeline/build.py`. ❌ = must fix before merging, ⚠️ = worth a look.", ""]
    common.REPORT.write_text("\n".join(head + sections), "utf8")
    common.SUMMARY.write_text("\n".join(head + summary + ["", "Full tables: `data/report.md`.", ""])[:60000], "utf8")
    data = {"prompts": game}
    common.GAME_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", "utf8")
    common.GAME_JS.write_text("// Generated by pipeline/build.py from data/prompts. Don't edit by hand.\n"
                              "window.GAME_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n", "utf8")
    print(head[2])
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
