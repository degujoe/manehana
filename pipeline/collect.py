#!/usr/bin/env python3
"""Collect rarity signals for every answer in data/prompts/*.yaml.

Needs internet access to Korean Wikipedia, Wikimedia pageviews and Wikidata,
so it normally runs on GitHub Actions (see .github/workflows/update-data.yml).

  python pipeline/collect.py              # every question
  python pipeline/collect.py joseon fish  # only these questions
  python pipeline/collect.py --offline    # only recompute word frequency (no internet needed)

Writes one file per question to data/signals/<id>.json. Those files are
generated: don't edit them by hand.
"""
import datetime
import json
import math
import re
import sys
import time
import urllib.parse

import common

UA = "manehana-rarity-bot/1.0 (https://github.com/degujoe/manehana)"
WIKI_API = "https://ko.wikipedia.org/w/api.php"
WD_API = "https://www.wikidata.org/w/api.php"
PV_URL = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
          "ko.wikipedia/all-access/user/{title}/monthly/{start}/{end}")

_session = None


def session():
    global _session
    if _session is None:
        import requests
        _session = requests.Session()
        _session.headers["User-Agent"] = UA
    return _session


MIN_GAP = 0.35          # seconds between requests: stay well under Wikimedia's rate limits
_last_call = [0.0]


def get_json(url, params=None, tries=7):
    import requests
    last = ""
    for attempt in range(tries):
        wait = MIN_GAP - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()
        try:
            r = session().get(url, params=params, timeout=30)
            if r.status_code == 404:
                return None
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                try:
                    pause = float(r.headers.get("Retry-After", ""))
                except ValueError:
                    pause = 0
                time.sleep(min(120, max(pause, 5 * 2 ** attempt)))
                continue
            if r.status_code >= 400:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                time.sleep(2 ** attempt + 1)
                continue
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = f"{type(e).__name__}: {e}"[:300]
            time.sleep(2 ** attempt + 1)
    raise RuntimeError(f"Request kept failing ({last}): {url} {params}")


# ---------------------------------------------------------------- Wikipedia

def page_info(titles, cache):
    """Fill cache[title] = {exists, title, disambig, qid, extract} for each title."""
    todo = [t for t in dict.fromkeys(titles) if t not in cache]
    for i in range(0, len(todo), 20):          # extracts allow 20 pages per request
        chunk = todo[i:i + 20]
        d = get_json(WIKI_API, {
            "action": "query", "format": "json", "formatversion": 2, "redirects": 1,
            "titles": "|".join(chunk), "prop": "pageprops|extracts",
            "ppprop": "disambiguation|wikibase_item",
            "exintro": 1, "explaintext": 1, "exlimit": 20, "exsentences": 3,
        })
        q = (d or {}).get("query", {})
        norm = {n["from"]: n["to"] for n in q.get("normalized", [])}
        redir = {r["from"]: r["to"] for r in q.get("redirects", [])}
        pages = {p["title"]: p for p in q.get("pages", [])}
        for t in chunk:
            final = redir.get(norm.get(t, t), norm.get(t, t))
            p = pages.get(final)
            if not p or p.get("missing") or p.get("invalid"):
                cache[t] = {"exists": False}
                continue
            props = p.get("pageprops", {})
            cache[t] = {
                "exists": True,
                "title": p["title"],
                "disambig": "disambiguation" in props,
                "qid": props.get("wikibase_item"),
                "extract": (p.get("extract") or "")[:400],
            }
        time.sleep(0.2)


def page_links(title):
    d = get_json(WIKI_API, {"action": "query", "format": "json", "formatversion": 2,
                            "titles": title, "prop": "links", "plnamespace": 0, "pllimit": "max"})
    pages = (d or {}).get("query", {}).get("pages", [])
    return [l["title"] for p in pages for l in p.get("links", [])]


def on_topic(info, context):
    text = info.get("title", "") + " " + info.get("extract", "")
    return any(w in text for w in context)


def resolve(answer, prompt, cache):
    """Find the Korean Wikipedia article for one answer.

    Returns (status, info, note). status is one of:
      ok        found an article about the right topic
      check     found an article, but its intro doesn't mention the topic words
      ambiguous only disambiguation pages found; pin the right title with `wiki:`
      missing   no article at all (counts as zero pageviews: a sign of rarity)
    """
    context = prompt.get("context", [])
    if answer.get("wiki"):
        candidates = [answer["wiki"]]
    else:
        names = [answer["name"]] + list(answer.get("aliases", []))
        candidates = [tpl.replace("{name}", n) for n in names for tpl in prompt["wiki_titles"]]
    page_info(candidates, cache)

    fallback, saw_disambig = None, []
    for t in candidates:
        info = cache[t]
        if not info["exists"]:
            continue
        if info["disambig"]:
            saw_disambig.append(info["title"])
            links = page_links(info["title"])
            name = answer["name"]
            picks = [l for l in links if l.startswith(name) and any(w in l for w in context)]
            if not picks:
                picks = [l for l in links if name in l and any(w in l for w in context)]
            if picks:
                page_info(picks, cache)
                real = [cache[l] for l in picks if cache[l]["exists"] and not cache[l]["disambig"]]
                if len(real) == 1:
                    return "ok", real[0], f"picked from disambiguation page {info['title']}"
                if len(real) > 1:
                    # several things share the name (e.g. many mountains called 남산): any of them is a
                    # valid answer, so the best-known one decides how familiar the answer is
                    best = max(real, key=lambda i: pageviews(i["title"]))
                    return "ok", best, (f"most-viewed of {len(real)} articles on disambiguation page "
                                        f"{info['title']}: " + ", ".join(i["title"] for i in real[:6]))
            continue
        if on_topic(info, context):
            return "ok", info, ""
        fallback = fallback or info
    if fallback:
        return "check", fallback, "article intro doesn't mention: " + ", ".join(context)
    if saw_disambig:
        return "ambiguous", None, "only disambiguation pages: " + ", ".join(saw_disambig)
    return "missing", None, "no Korean Wikipedia article"


def pageviews(title):
    today = datetime.date.today().replace(day=1)
    end = today - datetime.timedelta(days=1)                       # last day of last month
    start = (end.replace(day=1) - datetime.timedelta(days=330)).replace(day=1)
    url = PV_URL.format(title=urllib.parse.quote(title.replace(" ", "_"), safe=""),
                        start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"))
    d = get_json(url)
    if not d:
        return 0
    return sum(item.get("views", 0) for item in d.get("items", []))


NOT_WIKIPEDIA = {"commonswiki", "specieswiki", "wikidatawiki", "metawiki",
                 "mediawikiwiki", "sourceswiki", "wikimaniawiki", "outreachwiki"}


def sitelink_counts(qids):
    out = {}
    qids = [q for q in dict.fromkeys(qids) if q]
    for i in range(0, len(qids), 50):
        d = get_json(WD_API, {"action": "wbgetentities", "format": "json",
                              "ids": "|".join(qids[i:i + 50]), "props": "sitelinks"})
        for qid, ent in (d or {}).get("entities", {}).items():
            links = ent.get("sitelinks", {})
            out[qid] = sum(1 for k in links if k.endswith("wiki") and k not in NOT_WIKIPEDIA)
        time.sleep(0.2)
    return out


# ------------------------------------------------------------ official counts

def strip_markup(cell):
    cell = re.sub(r"<ref[^>]*?/>|<ref.*?</ref>", "", cell, flags=re.S)
    cell = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", cell)
    cell = re.sub(r"\{\{[^}]*\}\}|'''?|<[^>]+>", "", cell)
    if "|" in cell and not cell.strip().startswith("|"):
        cell = cell.split("|")[-1]                     # drop style="..." | value
    return cell.strip()


def table_counts(page, names):
    """Read a census-style table: for each row that names an answer, take the
    largest number in that row."""
    d = get_json(WIKI_API, {"action": "parse", "format": "json", "formatversion": 2,
                            "page": page, "prop": "wikitext", "redirects": 1})
    text = ((d or {}).get("parse") or {}).get("wikitext") or ""
    wanted = set(names)
    found = {}
    for row in re.split(r"\n\|-", text):
        cells = [strip_markup(c) for c in re.split(r"\|\||\n[|!]", row)]
        hit = None
        for c in cells:
            m = re.match(r"\s*([가-힣]+)", c)
            if not m:
                continue
            word = m.group(1)
            for cand in (word, word[:-1] if word.endswith("씨") else None):
                if cand and cand in wanted:
                    hit = cand
                    break
            if hit:
                break
        if not hit:
            continue
        nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]{1,}", " ".join(cells))]
        nums = [n for n in nums if not 1900 <= n <= 2100]          # skip years
        if nums:
            found[hit] = max(found.get(hit, 0), max(nums))
    return found, len(text)


def mentions(term):
    """How many Korean Wikipedia articles contain the exact term. Works even when the
    answer has no article of its own. Homonyms inflate it, which only ever makes an
    answer look MORE common: the safe direction (an easy answer can't score high)."""
    d = get_json(WIKI_API, {"action": "query", "format": "json", "list": "search",
                            "srsearch": f'"{term}"', "srwhat": "text", "srinfo": "totalhits",
                            "srlimit": 1, "srprop": ""})
    return ((d or {}).get("query", {}).get("searchinfo") or {}).get("totalhits")


# ------------------------------------------------------------ word frequency

_wf = None


def word_zipf(word):
    """Zipf frequency (0 = unseen, ~7 = the most common words). Reads the Korean
    list directly so MeCab isn't needed."""
    global _wf
    if _wf is None:
        from wordfreq import get_frequency_dict
        _wf = get_frequency_dict("ko")
    f = _wf.get(word)
    return round(math.log10(f) + 9, 2) if f else 0.0


# ---------------------------------------------------------------- main

def collect(prompt, offline=False):
    path = common.SIGNALS_DIR / f"{prompt['id']}.json"
    old = json.loads(path.read_text("utf8")) if path.exists() else {"answers": {}}
    out = {"id": prompt["id"], "answers": {}}
    cache = {}

    if offline:
        out["collected"] = old.get("collected")
        out["count_source"] = old.get("count_source")
    else:
        out["collected"] = datetime.date.today().isoformat()

    counts = {}
    if not offline and prompt.get("count_source"):
        counts, size = table_counts(prompt["count_source"]["page"], [a["name"] for a in prompt["answers"]])
        out["count_source"] = {"page": prompt["count_source"]["page"], "page_size": size,
                               "matched": len(counts), "of": len(prompt["answers"])}

    resolved, errors = {}, {}
    if not offline:
        for a in prompt["answers"]:
            try:
                resolved[a["name"]] = resolve(a, prompt, cache)
            except RuntimeError as e:      # one refused request shouldn't sink the whole question
                resolved[a["name"]] = ("error", None, str(e)[:200])
        qids = [info["qid"] for _, info, _ in resolved.values() if info]
        try:
            sl = sitelink_counts(qids)
        except RuntimeError:
            sl = {}

    for a in prompt["answers"]:
        name = a["name"]
        if offline:
            rec = dict(old["answers"].get(name, {"status": "not collected"}))
        else:
            status, info, note = resolved[name]
            rec = {"status": status, "note": note}
            try:
                if info:
                    rec["article"] = info["title"]
                    rec["qid"] = info.get("qid")
                    rec["pageviews"] = pageviews(info["title"])
                    rec["sitelinks"] = sl.get(info.get("qid"))
                elif status == "missing":
                    rec["pageviews"] = 0
                if prompt.get("count_source"):
                    rec["count"] = counts.get(name)
                # one-syllable answers (배, 북, 김) match far too many unrelated words to count
                rec["mentions"] = mentions(name) if len(name) >= 2 else None
            except RuntimeError as e:
                rec = {"status": "error", "note": str(e)[:200]}
            if rec["status"] == "error":
                errors[name] = rec["note"]
        if prompt.get("use_wordfreq"):
            bare = cache.get(name)
            rec["wordfreq"] = word_zipf(name)
            rec["wordfreq_homonym"] = bool(bare and bare.get("exists") and bare.get("disambig"))
        out["answers"][name] = rec

    common.SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", "utf8")
    if errors:
        print(f"::warning title=collect {prompt['id']}::{len(errors)} answers failed to collect "
              f"(kept their previous tier): {', '.join(list(errors)[:10])}")
    st = {}
    for r in out["answers"].values():
        st[r.get("status")] = st.get(r.get("status"), 0) + 1
    print(f"{prompt['id']:>10}: {len(out['answers'])} answers  " + "  ".join(f"{k} {v}" for k, v in sorted(st.items(), key=str)))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    offline = "--offline" in sys.argv
    failed = []
    for p in common.load_prompts():
        if args and p["id"] not in args:
            continue
        try:
            collect(p, offline=offline)
        except Exception as e:  # keep going so one bad question doesn't stop the rest
            import traceback
            tb = traceback.format_exc()
            print(tb, file=sys.stderr)
            where = [l.strip() for l in tb.splitlines() if l.strip().startswith("File ")][-1:]
            msg = f"{type(e).__name__}: {e} | {' '.join(where)}".replace("\n", " ")[:900]
            # GitHub shows ::error lines on the run page, even when logs can't be downloaded
            print(f"::error title=collect {p['id']} failed::{msg}")
            failed.append(p["id"])
    if failed:
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
