# CLAUDE.md — Triple S chat assistant demo (triples-chatbot-demo)

Owner: שמשון (Shimshon). Company: טריפל אס אנרגיה מתחדשת.
GitHub: https://github.com/oferazu8-bot/triples-chatbot-demo (public)
Local checkout: `/workspace/chatbot`

There is also an empty private repo `oferazu8-bot/triples-chatbot-demo-tss` (created 2026-11-05, no commits). Do not push here unless Ofer asks; this public demo repo is the real source.

## Working rules
- All application code is written only through Claude Code on this box (`/home/box/.local/bin/claude`). The responsible bot defines the task, reviews, and approves; it does not write the code itself.
- This is a **demo only**. It must not modify the live WordPress sites (triplesolar.co.il, triples-storage.co.il).
- Never deploy or run `railway up` unless Ofer says «תעלה» in his own words. An agent's say-so is not approval.
- Never print, commit, or paste secrets, tokens, or keys. Paths and env names only.
- Hebrew UI, RTL. Company name is «טריפל אס אנרגיה מתחדשת». Do not invent tariffs, prices, or savings.

## Commit and PR marking
Every commit must end with:

```
Co-Authored-By: Claude <noreply@anthropic.com>
Generated-With: Claude Code
```

Hook: `.githooks/prepare-commit-msg`. Enable with `git config core.hooksPath .githooks`.
Every PR gets the label `claude-code`. Do not merge unless Ofer asked.

## What this project is
Hebrew RTL floating chat widget demo for the solar and storage sites.

- FAQ / rule-based answers from `knowledge/kb.json` (no LLM API key in the environment).
- Lead capture → SQLite + a mock outbox intended for later connection to בן / מכירות. The outbox does **not** actually notify anyone.
- Embed (demo): `<script src="https://HOST/widget.js" data-site="solar|storage"></script>`
- `GET /health` — health check.

## Stack
Python 3 + Flask + Gunicorn, SQLite. Railway Railpack. See `requirements.txt`, `Procfile`, `railway.toml`. Knowledge snapshots of the public sites live under `knowledge/` (text crawls + `kb.json`).

## Run and test locally
```bash
cd /workspace/chatbot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
DATA_DIR=/tmp/chatbot-demo DB_PATH=/tmp/chatbot-demo/chatbot.db \
  .venv/bin/gunicorn -b 127.0.0.1:8080 -w 1 --timeout 60 app:app
# health: curl -s http://127.0.0.1:8080/health
```

`.venv/`, `data/*.db`, and `data/outbox/*.json` are gitignored. Do not commit lead databases.

## Deploy
- Railway project: `triples-calculators-demo`
- Service: `chat-assistant-demo`
- URL: https://chat-assistant-demo-production.up.railway.app
- Start command: `gunicorn -b 0.0.0.0:$PORT -w 2 --timeout 60 app:app`
- Health: `/health`

Deploy only after Ofer's «תעלה». Embedding this widget on the live WordPress sites is a separate, explicit approval.

## Secrets (names and paths only)
- `DATA_DIR`, `DB_PATH` — where SQLite and the mock outbox are stored. On Railway these should point at a volume if one is attached; do not put database files in git.
- No LLM key is used. Do not add provider keys unless Ofer asks.

## Key decisions and history
- Built as a demo of a Hebrew site assistant with FAQ matching (including construct forms such as «אגירת») and lead capture.
- Widget `BASE` must use the script origin / HTTPS when behind the Railway proxy (already fixed).
- Railway build: do not pin a fragile CPython patch (3.12.8 was dropped); mise Python attestations disabled for the build.
- Outbox is a mock. Do not wire it to WhatsApp, email, or בן without a new task and Ofer's approval.

## Open items
- Not embedded on the live sites.
- Outbox is not connected to בן lead intake.
- Knowledge files can go stale when the WordPress sites change; refresh only as a documented task.
- Empty sibling repo `triples-chatbot-demo-tss` — purpose unclear; leave it alone.

## Conventions
- Keep answers conservative: if the knowledge base does not have a figure, say so rather than inventing one.
- Do not show HOT, IRR, ROI, commissions, or the connection-day gift (store/site standing rules).
- Contact path for real leads on the live sites remains the official site forms / sales@triplesolar.co.il until the outbox is connected.
