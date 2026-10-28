# 만에 하나: instructions for Claude agents

만에 하나 is a Korean daily rare-answer game (like krillion.io). Seven questions a
day; rarer valid answers score more. The game is `index.html`; the questions live in
`data/prompts/*.yaml`; everything else in `data/` is generated.

Read `README.md` for how the pipeline works. This file covers what an agent may do
and the rules that keep the scores accurate.

## The one rule

**Tiers come from data, not from your judgment.** Never write `tier:` on an answer to
make a check pass or because an answer "feels" rare. The whole point of the game is
that an easy answer can't score high and a hard one can't score low, and the data is
what guarantees that. You may only set `tier:` when the data is demonstrably wrong
(for example a homonym inflating pageviews) and you must add `note:` with the evidence.

## Environment facts

- This cloud workspace can reach GitHub and package registries, but **not** Korean
  Wikipedia, Wikidata or Wikimedia pageviews. Don't try `pipeline/collect.py` here.
  The GitHub Actions workflow (`.github/workflows/update-data.yml`) runs it when you
  push to a branch named `agent/<something>`, then commits the regenerated
  `data/signals/`, `data/game.*`, `data/report.md` and `data/summary.md` back to that branch.
- `python pipeline/build.py` runs offline and is safe to run here at any time.
- Use WebSearch/WebFetch to research answer lists (Korean Wikipedia list articles,
  나무위키 to cross-check only, 국립국어원, official sites). Record what you used in `sources:`.

## Routine: weekly run

1. `git checkout -b agent/YYYY-MM-DD` from an up-to-date `main`.
2. Read `data/report.md` (from the latest merged data) and fix what it says, in this order:
   - ❌ problems (failed anchors, "too clever" gems, overrides without notes)
   - `ambiguous` / `check` answers: add `wiki: "<exact Korean Wikipedia title>"` to the
     answer once you've confirmed the right article exists (WebFetch it).
   - big "signals disagree" warnings: look for a wrong article or a homonym.
3. Add up to **3 new questions** (see below). Prefer ideas from `data/ideas.md`, and
   remove each idea from that file when you use it.
4. Commit, push, and wait for the workflow run on your branch to finish
   (`gh run watch` or poll `gh run list --branch agent/...`).
5. `git pull`, read `data/summary.md` and `data/report.md`, fix and push again. At most
   three rounds.
6. Open a pull request to `main` with `gh pr create`. Title: what you changed. Body:
   the new questions, the fixes, and anything still failing that needs a human
   (a Korean speaker) to decide. If checks still fail, open it as a draft PR.
7. Never merge your own PR and never push to `main`.

## Writing a new question

Copy an existing file in `data/prompts/` and keep the same fields.

- **Good questions** have at least 25 valid answers with a long tail: a handful
  everyone knows and many that only enthusiasts know. Korean-specific subjects work
  best. Avoid things that change often (current idols, product brands) and anything
  political or about private people.
- **answers:** every answer must be real and verifiable. Build the list from sources,
  not memory. Include the full set where one exists (all 27 Joseon kings, all stations
  on a line).
- **aliases:** other names players will type: native vs Sino-Korean words, common
  spelling variants of loanwords (주스/쥬스), old names (신천 → 잠실새내), short forms (홍대).
  An alias must never also be a different answer in the same question.
- **strip:** suffixes players add that should be ignored (역, 산, 김치, 씨).
- **wiki_titles / context:** how to find each answer's Korean Wikipedia article and
  check it's the right topic. Look at how existing files do it.
- **use_wordfreq:** true only if answers are ordinary words without other common
  meanings (fruit, kimchi). false for names, places, kings, surnames, instruments.
- **anchors:** 3 to 5 pairs `[very common, very obscure]` that any Korean adult would
  agree on. Never borderline pairs. Never change or remove an existing anchor to make
  the build pass; if an anchor fails, the data or the article choice is wrong.
- **gem:** the 만에 하나 answer: rare but satisfying to land on, something at least a
  few players will get. It must score at least 초롱아귀 (red) on the data.
- **sources:** list the URLs you built the answer list from.
- Every new question starts with `status: draft`. A human switches it to `live`
  after reviewing it.

## Tiers (for reference)

1 멸치 (grey) · 2 대왕오징어 (blue) · 3 초롱아귀 (red) · 4 덤보문어 (purple) ·
5 옆새우 = 만에 하나 (gold, exactly one per question)
