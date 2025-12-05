# Anki LLM Review Stats Exporter

Export your Anki **review history (revlog)** as **JSONL** so you can analyze it with an LLM (ChatGPT, Claude, local models, etc.) **without** using any API.

- One JSON object **per review** (not per card)  
- Optional filters: **time range, tags, minimum interval**  
- Flexible schema: **verbose** or **compact** (short keys, smaller size)  
- Designed for decks you want to deeply analyze (e.g. language learning, kanji, med school, etc.)


## Why?

Anki already tracks a lot of information about your learning:

- how often you review a card  
- how often you fail it  
- how intervals evolve  
- how long you spend answering  

This add-on exports that data into an **LLM-friendly JSONL file**, so you can drop it into ChatGPT/Claude etc. (or a local model) and instantly get:
- a diagnosis of your weakest cards and leeches  
- patterns in the words/kanji etc. you keep forgetting  
- concrete advice to fix your pacing, workload, and study method  


## Example
**JSONL** - 90 days of reviews from the *Kaishi 1.5k* (japanese vocab deck):
- total reviews: 22k+
- default size: 3.8M
- compact size: 2.7M

![](img/example.png?raw=true)

__Default__: 
```json
{"ts_iso": "2025-11-05T18:48:34Z", "ease": 3, "interval": 1, "last_interval": -600, "factor": 1089, "review_time_ms": 9519, "review_type": 2, "fields": ["事実", "じじつ"]}
{"ts_iso": "2025-11-05T18:48:39Z", "ease": 3, "interval": 5, "last_interval": -600, "factor": 1041, "review_time_ms": 5508, "review_type": 2, "fields": ["昔", "むかし"]}
{"ts_iso": "2025-11-05T18:48:44Z", "ease": 3, "interval": 1, "last_interval": -600, "factor": 1087, "review_time_ms": 4840, "review_type": 2, "fields": ["正直", "しょうじき"]}
{"ts_iso": "2025-11-05T18:49:24Z", "ease": 3, "interval": 1, "last_interval": -600, "factor": 1089, "review_time_ms": 40091, "review_type": 2, "fields": ["言葉", "ことば"]}
{"ts_iso": "2025-11-05T18:49:27Z", "ease": 3, "interval": 5, "last_interval": -600, "factor": 881, "review_time_ms": 2583, "review_type": 2, "fields": ["いやいや", "いやいや"]}
...... STRIPPED ......
```

__Compact__:
```json
{"t": "2025-11-05T18:48:34Z", "rt": 2, "e": 3, "i": 1, "li": -600, "f": 1089, "ms": 9519, "flds": ["事実", "じじつ"]}
{"t": "2025-11-05T18:48:39Z", "rt": 2, "e": 3, "i": 5, "li": -600, "f": 1041, "ms": 5508, "flds": ["昔", "むかし"]}
{"t": "2025-11-05T18:48:44Z", "rt": 2, "e": 3, "i": 1, "li": -600, "f": 1087, "ms": 4840, "flds": ["正直", "しょうじき"]}
{"t": "2025-11-05T18:49:24Z", "rt": 2, "e": 3, "i": 1, "li": -600, "f": 1089, "ms": 40091, "flds": ["言葉", "ことば"]}
{"t": "2025-11-05T18:49:27Z", "rt": 2, "e": 3, "i": 5, "li": -600, "f": 881, "ms": 2583, "flds": ["いやいや", "いやいや"]}
...... STRIPPED ......
```

➡️ **ChatGPT-5.1 Thinking** *(using compact jsonl)*:

<details>
  <summary>Result</summary>
I went through your 22k+ reviews and 1.4k cards. I'll walk you through what's going on and then give concrete tweaks you can make.

---

## 1. What's actually giving you trouble?

### 1.1. The worst "problem cards"

Looking at lapses (Again with previous interval > 0), total reviews, and how short the final interval still is, your biggest leeches are things like:

* **Adverbs / vague expressions**

  * 何とか / なんとか（58 reviews, 18 lapses, last interval 2d）
  * どうやら / どうやら（61 reviews, 16 lapses, last interval 4d）
  * どうも / どうも
  * どうにか / どうにか
  * 不意に / ふいに
  * 今更 / いまさら

* **Abstract Sino-Japanese nouns / ～する nouns**

  * 責任 / せきにん
  * 解放 / かいほう
  * 警戒 / けいかい
  * 真剣 / しんけん
  * 応援 / おうえん
  * 対応 / たいおう
  * 提案 / ていあん
  * 注意 / ちゅうい
  * 回復 / かいふく
  * 解決 / かいけつ
  * 精神 / せいしん
  * 現状 / げんじょう
  * 評価 / ひょうか
  * 終了 / しゅうりょう
  * 支配 / しはい
  * 印象 / いんしょう

* **Look-alike / sound-alike clusters**

  * 性格 / せいかく
  * 正確 / せいかく
  * 正解 / せいかい
  * 通う / かよう & 通る / とおる
  * 直す / なおす（vs. 直る etc.）
  * 防ぐ / ふせぐ
  * 限る / かぎる
  * 挟む / はさむ
  * 染まる / そまる

For a lot of these, you have:

* **40–70 reviews per card**
* **10+ lapses**
* **Final intervals still only 1–6 days**
* **Long response times (often 10–20+ seconds on average for these specific cards)**

So these really are classic SRS leeches, not just "slightly hard" items.

---

## 2. What kinds of words and kanji are hardest for you?

### 2.1. Script type

Across *all* reviews:

* **Kanji-only words**

  * 12,300 reviews
  * Again rate ≈ **25%**
* **Kanji + kana mixed (e.g. 解決する, 改めて)**

  * 8,258 reviews
  * Again rate ≈ **21%**
* **Pure hiragana words (かなり, ごめん, etc.)**

  * 1,651 reviews
  * Again rate ≈ **21%**

Among your problem cards, **kanji-only words are heavily over-represented**:

* In the whole deck, kanji-only = **47%** of cards.
* Among problem cards, kanji-only = **64%**.

So: your **main pain point is kanji compounds with no kana on the front**.

### 2.2. Kanji that appear again and again in problem cards

In the top ~150 problem cards, the kanji that repeat most often include:

* **解**, **通**, **用**, **信**, **意**, **事**
* **正**, **直**, **確**, **態**, **度**, **実**

These form many confusing families:

* 解放 / 解決 / 解消…
* 正確 / 正解 / 正直 / 性格 (plus all the せい〜 words)
* 通う / 通る / 交通 / 通過…

So your **errors are driven by interference** between very similar kanji and very similar readings/meanings — classic intermediate-advanced Japanese problem.

### 2.3. New cards vs. difficulty

You also had *huge* spikes of new cards at the beginning:

* 2025-09-06: **165 new cards** (262 total reviews, again rate ≈ 32%)
* 2025-09-07: **117 new cards**
* 2025-09-08: **87 new cards**
* Average over the entire period: ~**18 new cards/day**
* Last two weeks: ~**9–10 new cards/day** (much more reasonable)

There's a clear pattern: days with lots of new cards have **higher again rates** and longer answer times. So overload is a big part of where these leeches came from.

### 2.4. Time of day

Again rate by hour (approx):

* Best zones (fewer errors):

  * 08:00 → ~**9%** Again (few data points but very good)
  * 13:00–14:00 → **16–17%** Again
* Hard zones (more errors):

  * 16:00 → **28%** Again
  * 17:00–20:00 → **27–30%** Again
  * 22:00 → **44%** Again (few reviews but terrible performance)

You clearly **remember better earlier in the day / early afternoon** and are **much more error-prone late afternoon and night**.

---

## 3. Methodological issues I see

### 3.1. Overload of new material early on

The early days with 100+ new cards/day correlate with:

* high again rates (around **28–30%** in some early weeks),
* lots of cards stuck in short-interval loops.

That's textbook **encoding overload**: you tried to take in way more than your brain could consolidate, especially for abstract kanji compounds.

### 3.2. Overall retention a bit low for FSRS

Across all reviews:

* Global again rate ≈ **23%** → retention ≈ **77%**.
* Review cards only: again ≈ **19%** (retention ≈ **81%**).
* Learn steps: again ≈ **47%** (almost half of new-card attempts fail).

FSRS tends to work best around **85–90% target retention**.
You're running a bit "too hard mode": okay for motivation if you accept frustration, but it helps explain the number of leeches.

### 3.3. Only Again/Good + slow "Good"

You only use **Again (1)** and **Good (3)**. That's fine *if*:

* "Good" = *quick, confident recall.*

But in your data, about **12% of your Good presses take longer than 12 seconds**. That usually means: your memory is weak or the answer is half-guessed. FSRS then *overestimates* how stable that memory is, stretches the interval too much, and you forget it next time → lapse loop.

So a lot of your "difficulties" are actually **borderline recalls being graded too generously**.

### 3.4. Card design: kanji → reading only

All your notes seem to be:

> Front: kanji word
> Back: reading in kana

No meaning, no sentence, no hint.

This is the hardest possible type for:

* abstract kanji compounds,
* clusters like 性格 / 正確 / 正解,
* nuance-heavy adverbs (何とか, どうやら, どうも, どうにか).

For these, the brain *needs* context and meaning links, not just "this squiggle → this sound".

---

## 4. How to understand your learning difficulties

Putting it together:

1. **Interference between similar items**

   * Groups like 解放 / 解決 / 回復, 性格 / 正確 / 正解, 通う / 通る, etc. are "crowding" each other.
   * You're often trying to recall **the exact reading of the exact compound** without any strong semantic anchor.

2. **Abstract vocabulary without context**

   * Words like 責任, 対応, 提案, 精神, 現状, 評価, 支配, 印象 are very context-dependent.
   * Without a sentence or mental scenario, they're just floating labels.

3. **Overloaded initial phase**

   * The huge burst of early new cards created a pool of "half-learned" items that became chronic leeches.

4. **Tired-time reviews**

   * Many high-error reviews are in late afternoon/evening, when your attention and working memory are lower.

5. **Grading too leniently**

   * Slow, hesitant recalls are marked Good, so FSRS gives intervals that are slightly too long for your actual memory strength.

---

## 5. Concrete recommendations

### 5.1. Handling leeches (what to do with those nightmare cards)

I'd treat a card as a **leech** if either:

* ≥ **8 lapses**, or
* ≥ **40 reviews** with again rate ≥ **40%** and final interval still ≤ ~7 days.

You currently have ~40–50 such cards.

**For those:**

1. **Suspend from the main flow.**
   Don't keep hammering them in normal reviews. Tag them as `leech` and bury/suspend.

2. **Rebuild the card with more cues.** For example:

   * Add **a short Japanese sentence** showing a clear context.
   * Add a **very short meaning** or keyword (even just in English or your native language).
   * Add a **little hint about the kanji** ("解 = to untie / explain", "警 = warn", etc.).

3. **Break big confusion sets apart.**
   For things like:

   * 性格 vs 正確 vs 正解
   * 解放 vs 解決 vs 回復
     Make a mini note outside Anki where you:
   * write each word, an example, and a distinct explanation,
   * maybe create one *comparison card* like:

     > Front: 「‘solve a problem' = ？」
     > Back: 解決する
     > and one like:
     > Front: 「‘free prisoners' = ？」
     > Back: 解放する

4. **Re-introduce them slowly, not all at once.**
   Once you've rebuilt, drip them back in at **1–2 per day** max, and only when you have mental bandwidth.

5. **If a leech still won't die, accept "passive only".**
   Maybe you treat some words as:

   * okay to understand in reading (you'll get them from context),
   * but not worth mastering as active recall right now.
     For those, it's totally fine to keep them only in immersion/reading and drop the card.

---

### 5.2. Adjusting pacing and load

1. **New cards/day**

   * The last two weeks you're averaging ~9–10 new cards/day → this is a *good* range for your level.
   * I'd set a hard cap around **10–15 new cards/day** for this kind of abstract, kanji-heavy vocab.
   * Definitely avoid spikes like 50–100 new in one day again.

2. **Daily reviews**

   * You're doing ~**240–300 reviews/day**, with peaks around **400**.
   * If you feel mentally fine, 250–300 is okay.
   * On days you're tired or busy, it's better to **reduce new cards to 0** than to skip reviews. FSRS will keep your intervals reasonable.

3. **Time-of-day strategy**

   * Put your **hardest reviews (mature & leeches, kanji-heavy)** in a session around **late morning or early afternoon (10:00–14:00)**.
   * Use late afternoon/evening sessions mostly for:

     * easier reviews,
     * "cleanup" work,
     * or even just reading / listening practice instead of Anki.

4. **Stricter Good/Again rule**

   * Decide on a **personal rule**, for example:

     * If it takes **>10 seconds**, or
     * If you feel you "just guessed",
     * or if you mentally needed to go through multiple wrong candidates first
       → **press Again.**
   * This will raise your short-term again rate a bit, but it will **reduce long-term leeches** and frustration.

---

### 5.3. Specific strategies for kanji and confusing compounds

1. **Add a minimal semantic anchor to kanji-only cards.**

   * Without bloating the card, add:

     * a 1–3 word gloss, or
     * a short phrase like "responsibility; duty" for 責任.
   * Even a **keyword** is enough to give your brain another hook.

2. **Use "kanji families" outside of Anki.**
   Take your frequent leech kanji like 解, 通, 正, 確, 直, 意, etc. and:

   * Make a small page per kanji:
     * kanji,
     * basic meaning,
     * 3–4 common words you're actually studying.
   * Group your problem words on those pages so your brain sees patterns instead of isolated noise.

3. **Targeted practice for near-synonym sets.**
   For clusters:

   * 性格 / 正確 / 正解

   * 解放 / 解決 / 回復

   * 通う / 通る
     do a **5–10 minute comparison drill**:

   * Write each word by hand.

   * Say the reading out loud.

   * Say a short example sentence (even a simple one).

   * Explicitly say the contrast:

     * "正確 = correct (no mistakes); 正解 = the right answer on a test; 性格 = personality."

   You can optionally make **one extra card per set** that directly asks you to distinguish them (e.g. a cloze sentence where only one fits).

4. **Limit pure "kanji → reading" drills for the worst offenders.**
   For leechy compounds, it might be better to flip the direction:

   * **Back = kanji** (with sentence), **Front = meaning or audio or reading**.
   * That way you test understanding & recognition rather than strict production of the reading, reducing interference pressure.

   You don't have to change the whole deck; just do this for a subset of chronic leeches.

5. **Writing practice for a small subset of kanji.**
   For the most problematic kanji (e.g. 解, 憶 if you have it, etc.):

   * Pick **5–10 kanji** max.
   * Write them by hand from memory in a notebook a few times while saying the reading & a word they appear in.
   * This isn't to become a calligrapher; it's to deepen the **orthographic and motor memory**, which stabilizes recognition and reduces confusion.

---

### 5.4. Working with FSRS specifically

Given your stats:

* Review again rate ~19% → okay but could be smoother.
* Learn again rate ~47% → new material is too hard or too dense.

I'd suggest:

1. **Reduce "new" difficulty rather than tweaking FSRS first.**

   * Fewer new cards/day (which you already started doing).
   * Better encoding (add meaning/sentence on leech-prone vocab).

2. **If you can edit FSRS settings:**

   * Make sure the target retention isn't set ridiculously high (≥95%) for this deck.
     A target around **90%** for vocab is usually a sweet spot: fewer lapses, less stress.

3. **Monitor again rate by deck after these changes.**

   * If, after adding context + lowering new cards, your review again rate stays around **15–20%** and you *feel* okay, you're in a good zone.
   * If it's >25% and you're annoyed, back off further on new cards or rebuild more leeches.

---

## 6. TL;DR – What to actually change this week

If you want a simple "do this now" list:

1. **Cap new cards** at **10–15/day** for this deck (you're already close to this).
2. **Adopt a Good rule:**

   * > 10 seconds or shaky recall = **Again**, not Good.
3. **Suspend and tag the worst leeches** (those with ≥8 lapses or 40+ reviews + still short intervals).
4. **Rebuild 5–10 of those leeches** with:

   * a tiny meaning,
   * a sentence,
   * and/or a note distinguishing it from its "twin" words.
5. **Schedule your hardest reviews in the 10:00–14:00 window** when you're clearly performing best; keep late-evening sessions lighter or skip them.
6. **Do one short "kanji family" session** a couple of times this week:

   * Pick a troublesome kanji (e.g. 解 or 正),
   * list the confusing words,
   * make quick comparisons and example sentences.

If you'd like, next step I can:

* take one of your "problem families" (e.g. 解放・解決・回復 or 性格・正確・正解)
* and help you design concrete example sentences & mnemonics tailored to how you seem to be forgetting them.

</details>

*https://chatgpt.com/share/6932fed8-c6a8-8000-8477-1049d95cb85e*


## Requirements / Compatibility
Tested with Anki 2.1+ (Qt6)

## Installation

1. Close Anki.  
2. Clone or download this repository.  
3. Place the folder in your Anki `addons21` directory, for example:
   - **macOS**: `~/Library/Application Support/Anki2/addons21/llm_review_stats`  
   - **Windows**: `%APPDATA%\Anki2\addons21\llm_review_stats`
   - **Linux**: `~/.local/share/Anki2/addons21/llm_review_stats`

4. Restart Anki.

You should now see a new menu entry:

> **Tools → Export LLM Stats…**

## Usage

1. Open Anki.  
2. Go to **Tools → Export LLM Stats…**  
3. A dialog will appear with several options.

### 1. Deck

- **Deck**: choose the root deck you want to analyze.  
  All **subdecks are included** automatically.

### 2. Time range

You can choose a predefined range:

- Last day (24h)  
- Last week (7 days)  
- Last month (30 days)  
- Last 3 months (90 days)  
- Last year (365 days)  
- All history  

Or use:

- **Custom days (optional)**:  
  - If `> 0`, it overrides the predefined range.  
  - If `0`, the predefined range is used.

Time filtering is based on `revlog.id` (timestamp in milliseconds).

### 3. Field selection

- **Fields to export**:  
  - Example: `0,1,2` → export field 0, 1 and 2 of each note.  
  - Leave empty → export **all fields**.
- All fields are **cleaned**:
  - `[sound:...]` removed  
  - `<img ...>` removed  
  - HTML tags stripped  
  - whitespace normalized  

### 4. Filters

- **Filter by tags**  
  - Example: `grammar,verbs`  
  - Only reviews whose note has **at least one** of these tags will be exported.  
  - Leave empty → no tag filter.

- **Minimum interval (days)**  
  - Example: `21` → only export reviews where the *new interval* (`ivl`) is ≥ 21 days (i.e. more mature cards).  
  - `0` → no interval filter.

### 5. Export schema options

- **Include card/note/deck IDs**  
  - Adds `card_id`, `note_id`, `deck_id` fields.  
  - Useful if you want to link reviews back to specific cards or notes.

- **Include deck name**  
  - Adds `deck_name` (`"<unknown>"` if not found).

- **Include raw timestamp (ts_ms)**  
  - Adds `ts_ms` (integer in milliseconds since Unix epoch) in addition to the human-readable timestamp.

- **Compact schema (short keys, no IDs/deck name)**  
  - When checked, output uses **short keys**:
    - smaller files  
    - fewer tokens when pasting into an LLM  
  - In compact mode, IDs and deck name are suppressed regardless of the other checkboxes.

### 6. Output file

- **File**: choose where to save the `.jsonl` file.  
  Default: inside your profile folder as `llm_review_stats.jsonl`.

## Output format

The add-on writes a **JSONL file**: one **JSON object per line**, each describing a single review.

### Default schema

When **Compact schema** is **unchecked**, each line looks like this (depending on options - here's from `Kaishi 1.5k` deck with fields `0,1`):

```json
{
    "ts_iso": "2025-12-03T16:55:49Z", 
    "ease": 3, 
    "interval": 2, 
    "last_interval": 2, 
    "factor": 1085, 
    "review_time_ms": 3077, 
    "review_type": 1, 
    "fields": ["手段", "しゅだん"]
}
```

Which keys appear depends on your schema options:

**Always present (verbose mode):**

- `ts_iso` – ISO8601 timestamp (UTC)  
- `ease` – selected button (1=Again, 2=Hard, 3=Good, 4=Easy)  
- `interval` – new interval (days)  
- `last_interval` – previous interval (days)  
- `factor` – ease factor (e.g. 2500 = 2.5×)  
- `review_time_ms` – answering time (milliseconds)  
- `review_type` – type of review  
  - `0` = learn  
  - `1` = review  
  - `2` = relearn  
  - `3` = filtered  
- `fields` – list of cleaned note fields `[field0, field1, ...]`

**Optional (if checkboxes are enabled):**

- `ts_ms` – raw timestamp in ms since epoch  
- `card_id`, `note_id`, `deck_id` – numeric IDs  
- `deck_name` – deck name as seen in Anki  

### Compact schema

When **Compact schema** is **checked**, each line uses **short keys**:

```json
{
  "t": "2025-12-05T12:02:51Z",
  "rt": 1,
  "e": 3,
  "i": 4,
  "li": 4,
  "f": 1082,
  "ms": 3937,
  "flds": ["通う", "かよう", "aller et revenir, fréquenter"]
}
```

Schema:
- `t` – ISO8601 timestamp (UTC)  
- `rt` – review type (0=learn, 1=review, 2=relearn, 3=filtered)  
- `e` – selected button (1=Again, 2=Hard, 3=Good, 4=Easy)  
- `i` – new interval (days)  
- `li` – previous interval (days) 
- `f` – ease factor (e.g. 2500 = 2.5×)  
- `ms` – answering time (milliseconds)  
- `flds` – list of cleaned note fields `[field0, field1, ...]`  

> **Important:** LLMs don't automatically know what `rt`, `e`, etc. mean.  
> You should explain this schema once at the start of your prompt.


## Using the export with an LLM

Because JSONL files can be large and LLMs have context limits, a practical approach is:

- Export only what you need:
   - a specific deck  
   - a reasonable time range (e.g. last 90 days)  
   - optional filters by tags or minimum interval  
- use the compact version if needed

### Example prompt (compact schema, Kaishi 1.5k deck)

Here's an example prompt you can adapt, assuming you used **compact schema**:

```md
I'm attaching a JSONL file containing my review stats from my Japanese vocab Anki deck, with:
– the text fields (words, translations)
– statistics over days (number of reviews, number of lapses, etc.)

Each line is a JSON object with this compact schema:  
- t: ISO timestamp of the review (string)  
- rt: review type (0=learn, 1=review, 2=relearn, 3=filtered)  
- e: ease button pressed (1=Again, 2=Hard, 3=Good, 4=Easy)  
- i: new interval in days (integer)  
- li: previous interval in days (integer)  
- f: ease factor used by Anki (integer, e.g. 2500 = 2.5x)  
- ms: time spent answering in milliseconds (integer)  
- flds: list of text fields of the note, usually [front, back, extra]  

Analyze this data as a Japanese teacher and a specialist in memory & learning.

Identify:
– the cards that cause me the most problems
– the types of words/kanji that frequently appear in my errors
– the methodological issues (reviewing, overload, etc.) that you detect.

Give me concrete recommendations to:
– understand my learning difficulties
– handle "leech" cards
– adjust my pacing
– and specifically manage difficulties related to kanji (confusion, overload...).

I'm using FSRS (+ only "again" or "good").  
```

## Notes & limitations

- Export is **read-only**: it never modifies your collection.  
- For very large collections, exporting **all history** may create a big file.  
  Use time range, tags, and minimum interval to narrow down.  

## License

This project is licensed under the MIT License.

MIT License

Copyright (c) [2025] [Jaybird1291]

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
