# DraftIQ

A fantasy football draft assistant, rebuilt as a Flask web app.

## Run it

```
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000

A sample player pool (`uploads/sample_players.csv`) loads automatically so
you can try it immediately. To use your own player rankings, go to
**Setup** and upload a CSV with columns like: `player` (or `name`),
`pos` (or `position`), `team`, `rank`, `adp`.

## What changed from your original notebook code

- **Consolidated 3 competing versions** of `get_draft_recommendations()`,
  2 versions of `calculate_draft_urgency()`, and 6 identical copies of
  `calculate_position_urgency()` down to one each (kept the most-developed
  version in every case).
- **Fixed a stale-cache bug**: player tiers used to be calculated once at
  load time and never recalculated as the draft progressed. They now
  recompute against currently-available players.
- **Fixed an undefined-variable bug** in `availability_score()`
  (referenced a `drafted_players` global that didn't exist) — this
  function was unused elsewhere and was dropped.
- **Fixed team-index inconsistency** between 1-indexed `MY_TEAM`/
  `settings["user_slot"]` and 0-indexed draft math.
- Dropped `what_if_i_wait()`'s "simulation-based" variant, which called
  `simulated_next_pick_probability()` — a function that was never defined
  anywhere in the source and would have crashed on use.
- Replaced all Colab-only `display()`/`print()` output with return values
  so the Flask layer can render them as JSON/HTML.
- Moved all mutable state (`league`, `draft_state`, `players_df`) off of
  module-level globals and onto a `DraftIQEngine` class instance, since
  globals mutated on import don't behave correctly in a web server.
- Hardcoded `/content/players.csv` path replaced with a file upload flow.

## Structure

- `engine.py` — all draft logic (scoring, tiers, urgency, recommendations,
  simulation) as a single `DraftIQEngine` class.
- `app.py` — Flask routes / JSON API wrapping the engine.
- `templates/index.html` — single-page dashboard (vanilla JS, no build step).
