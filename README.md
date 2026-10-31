# 만에 하나

A Korean daily rare-answer game. Seven questions a day, the same for everyone.
Common answers keep you in shallow water; rare ones sink you deeper.

## What's where

| Path | What it is | Edit it? |
|---|---|---|
| `index.html` | The game | Yes, for design and game rules |
| `data/prompts/*.yaml` | One file per question: wording, answers, aliases, checks | **Yes, this is the database** |
| `data/ideas.md` | Ideas for new questions | Yes |
| `data/days/YYYY-MM-DD.js` | One file per day: that day's 7 questions with their answers and tiers, frozen once the day starts in Korea | No (generated) |
| `data/days/schedule.md` | Which questions run on which day, and where questions repeat | No (generated) |
| `data/report.md` | Every answer's numbers, tier and warnings | No (generated) |
| `data/signals/*.json` | Raw numbers collected for each answer | No (generated) |
| `data/game.js`, `data/game.json` | What the game loads | No (generated) |
| `pipeline/` | The collector and scorer | Only to change how scoring works |
| `CLAUDE.md` | Rules for the background Claude agent | Yes |

## How rarity is decided

For every answer the collector (`pipeline/collect.py`) finds its exact Korean
Wikipedia article and gathers:

- **pageviews** of that article over the last 12 months (the main signal),
- **languages**: how many Wikipedias have an article about it,
- **word frequency**, for questions where answers are everyday words,
- **official counts** where a table exists (census population for surnames).

The scorer (`pipeline/build.py`) ranks each answer against the others in the same
question and splits them into tiers: 멸치 (grey), 대왕오징어 (blue), 초롱아귀 (red),
덤보문어 (purple). The 만에 하나 gem (옆새우, gold) is chosen by hand in each file.

Accuracy checks run every time:

- **Anchors**: pairs like 세종 > 경종 that must come out in that order, or the update is blocked.
- **Ceiling / floor**: an answer that any signal says is very common can't go below blue;
  one that every signal says is rare can't be grey or blue.
- **Too clever**: the gem must score at least red on the data.
- **Wrong article**: answers whose article looks off-topic or ambiguous are left out of
  the scoring and listed in the report so you can pin the right title with `wiki:`.

## Daily questions

The game loads the file for today's date in Korea, e.g. `data/days/2026-11-01.js`.
Each file is a full copy of that day's 7 questions, so a past day always plays
exactly as it did, even after tiers or answers change.

A GitHub job (**Schedule daily questions**) runs every evening Korea time and keeps
the next week of files ready. It picks questions that have never been used first,
then the ones used longest ago, and avoids repeating a question within 60 days when
the pool allows. Tomorrow's file keeps its questions but picks up newly approved
tiers; days that have started are never changed. `data/days/schedule.md` lists every
day and flags repeats.

To choose a future day's questions yourself:

```
python pipeline/schedule.py --set 2026-11-05 joseon,fish,fruit,island,kimchi,gugak,line2
```

## Updating

GitHub runs the collector every Monday (and whenever a question file changes on
`main`). It opens a pull request called **Rarity data refresh** with the new tiers and
a summary. Read it, then **Merge**. Nothing changes in the live game until you merge.

To run it yourself: **Actions → Update rarity data → Run workflow**.

## Editing a question

Open a file in `data/prompts/`, change it, commit. To add an answer:

```yaml
  - name: "철종"
    aliases: ["강화도령"]
```

To fix an answer that the report says has the wrong Wikipedia article:

```yaml
  - name: "태조"
    wiki: "조선 태조"
```

New questions start as `status: draft` and don't appear in the game until you change
that to `status: live`.

## Running locally (optional)

Opening `index.html` in a browser plays the game with the current `data/game.js`.
To rebuild the data on your own computer you need Python 3:

```
pip install pyyaml requests wordfreq
python pipeline/collect.py   # needs internet, takes a few minutes
python pipeline/build.py     # scores, checks, writes data/report.md
```
