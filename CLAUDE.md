# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project identity

A Korean-language text RPG (Flask backend + vanilla-JS frontend) whose actual purpose, per [PROJECT_GOAL.md](PROJECT_GOAL.md), is a **simulation-driven balance-tuning and player-behavior-analysis system** — the game is the data-collection vehicle, not the end goal. Battle math lives in a single engine (`ai/battle/`) shared by real Flask battles and headless Monte Carlo simulation, specifically so balance conclusions drawn from simulation transfer to live play. Keep that sharing intact when touching battle mechanics — don't fork logic between "real" and "simulated" paths.

`README.md`'s "실행"/"검증" commands (`python3 Main.py`, `ai.Battle_Engine` imports) describe an earlier pre-Flask CLI layout — `Main.py` no longer exists. Use the commands below instead.

## Commands

Run the dev server:
```bash
python3 App.py                       # http://localhost:5000, FLASK_DEBUG=0 by default (see .env.example)
```

Production-like run (what Render actually starts, `Procfile`):
```bash
gunicorn App:app --workers 1 --threads 8 --worker-class gthread --bind 0.0.0.0:$PORT
```
`--workers` must stay at 1 — `BattleSession`/`BalanceHook` (the `battle`/`hook` keys in a session dict) are in-memory only and never persisted (see Architecture below); a second worker process would not see them.

Tests are standalone scripts, not pytest — no test runner config exists. Run one file directly from the project root:
```bash
python3 TestFile/test_element_fix.py     # single test file
for f in TestFile/test_*.py; do python3 "$f"; done   # full quick suite
```
Each prints `✅`/`❌` per assertion and exits non-zero on failure. `TestFile/montecarlo.py` is a long-running balance simulation (many thousands of simulated battles), not a pass/fail regression test — don't include it in a "run the suite" pass.

Local DB is SQLite at `ai_rpg.db` (gitignored, auto-created by `init_db()` on boot). Delete the file to reset local state; schema changes need no migration tool since `init_db()` just calls `Base.metadata.create_all()`.

## Architecture

### Backend layering (bottom to top)
- `DB/` — SQLAlchemy models (`Models.py`) + `get_session()` context manager (auto commit/rollback/close). `DATABASE_URL` env var switches SQLite → Postgres with no code change.
- `game/` — domain models: `Player_Class.py`, `Enemy_Class.py`, `Inventory.py`, `Lv.py` (leveling), `Skill.py`, `Rewards.py`, `Map.py` (node-map generation/spawn tables).
- `ai/battle/` — the stateless battle engine (`Entity`, `ATB`, `Actions`, `Elements`, `Damage`, `Skills`, `Items`, `Engine`, `MonsterKit`). Pure calculation: no Flask, no session state. Its `__init__.py` docstring states the internal dependency layering — read it before adding a new module here.
- `ai/Battlesession.py` + `ai/battle_session/` — the stateful, Flask-facing wrapper. `BattleSession` (in `Battlesession.py`) is composed from mixins in the `battle_session/` package (`Targeting`, `ATB_Flow`, `Rewards`, `Player_Actions`, `Enemy_Actions`, `State`, `Battle_Log`) — `step(action)` is the only entry point routes call. When changing turn/reward/logging behavior, find the right mixin rather than adding to `Battlesession.py` itself.
- `ai/Auto_AI.py` — `PlayerAI`/`EnemyAI` decision logic (skill/target selection), used by both live battles and simulation.
- `app/` — Flask blueprints, one per feature: `Game.py` (new game/status/skills/items), `Battle.py`, `Inventory.py`, `Rest.py`, `Ranking.py`, `Map.py` (node-map traversal). `Shared.py` holds cross-blueprint state/helpers — see session persistence below. Blueprints are imported in `app/__init__.py` by capitalized filename (`from .Game import game_bp`, matching the committed filename case) — this matters because deployment runs on case-sensitive Linux while local dev is often case-insensitive macOS; a filename/import-case mismatch works locally and 404s in production.
- `core/` — `Balance_Hook.py` (background simulation feeding live balance decisions), `RedisCache.py` (thin optional cache, see below).

### Session persistence (3-tier, sticky-session design)
`app/Shared.py`'s `GAME_SESSIONS` dict is a per-worker in-memory cache — `_get_session()` reads memory → Redis → DB (`PlayerState` table) in that order and backfills upper tiers on a hit. `_persist_session()` write-throughs to Redis + DB on every mutating (non-GET) request via the `after_request` hook in `app/__init__.py`. Only `player`/`inventory`/`map`/`chapter`/`gold`/turn counters are serialized — `battle` (the live `BattleSession`) and `hook` (`BalanceHook`) are deliberately **not** persisted; recovering a session after a worker restart always reconstructs with `battle=None`, so any in-progress fight is lost and must be restarted (the frontend's `battleAction()` in `Actions.js` handles the resulting 400 by resyncing to the map instead of retrying). This whole design assumes sticky sessions (same user → same worker) and a single gunicorn worker; scaling workers safely would need this design revisited, not just a `--workers` bump.

### Frontend: no build step
`static/js/*.js` are plain scripts loaded via `<script>` tags in `static/index.html`, in dependency order (`Api.js` → `State.js` → `CharSprite.js` → `BattleSequencer.js` → … → `Main.js` last). There is no bundler and no module system — everything is global-scope. Adding a new JS file means inserting a `<script>` tag at the correct position in that load order (before its first caller, after anything it depends on), not just dropping the file in `static/js/`.

`CharSprite.js` drives sprite-sheet battle animations (`setCharState`); `State.js`'s `CHAR_IMAGES` table maps each character/state to either a static PNG path or a `{src, type:'sheet', frames, fps, loop}` descriptor. `BattleSequencer.js` derives actual animation wait-times from `frames/fps` rather than fixed constants — keep it that way when adding new sheets so timing doesn't drift from what's actually on screen.

### Balance-curve stacking (read before touching monster stats)
Enemy stats going into a fight are the product of **four independently-defined multipliers**, spread across two files: `GRADE_MULT` (하/중/상) and `_level_curve_mult()` (per-level scaling) in `game/Enemy_Class.py`'s shared `_apply_grade()`, then `STAT_SCALE`/`ELITE_STAT_SCALE` (multi-enemy discount) and `_early_game_multi_scale()` (extra early-level dampener) in `app/Map.py`. Both files cross-reference each other in comments precisely because no single function reasons about the combined effect. This combination was tuned empirically against `TestFile/montecarlo.py`-style full sweeps (all monsters × levels 1–25 × all jobs) to hit a target win-rate band — changing any one multiplier in isolation risks re-breaking that balance; re-run a full sweep after any change here, don't eyeball it. Boss factories (`Make_MidBoss`/`Make_FinalBoss`) intentionally bypass `_apply_grade()` and are tuned directly.

### Elemental system
`ai/battle/Elements.py`'s `ELEMENT_IMMUNITY_BY_ENEMY_TYPE` + `is_element_immune()` gate elemental damage; `ai/Auto_AI.py`'s skill-scoring must check immunity before ranking a skill (an AI that ignores this will repeatedly pick a 0-damage move against an immune target instead of falling back).
