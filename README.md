# Accountability App

A personal habit-tracking app with a shared point pool and a Discord bot for
social accountability. You track good/bad habits daily - failures add points
to a pool; friends can see and redeem those points on rewards via Discord.

This is a personal project — not designed for anyone else to deploy or use.

## How it works

- **Good habits**: left unchecked at day's end → adds points.
- **Bad habits**: checked during the day → adds points instantly, and
  triggers a Discord alert ~1 minute later (so a misclick can be undone).
- Points are shared between a current balance (spendable) and a
  lifetime points (never decreases).
- Rewards can be redeemed from the website or via the Discord bot (`/rewards`,
  `/redeem`). Redemptions are tracked separately so you can mark them
  "completed" once you actually get around to them.
- A nightly job (11:59 PM Eastern) scores any good habits left unfinished
  and posts a daily report to Discord.

The bot runs inside the same process as the website (via FastAPI's
`lifespan`), not as a separate service — this was a deliberate choice to
stay on Render's free tier. An external uptime monitor pings `/health`
every few minutes to keep the service from spinning down.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in real values
uvicorn app.main:app --reload
```

Required environment variables:
- `DATABASE_URL` — Supabase Postgres connection string
- `SITE_PASSWORD`, `SESSION_SECRET` — not yet wired into actual login
  protection (planned, not implemented)
- `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID` — for the bot half

## Deployment

Deployed as a single Render web service (free tier). Build command:
`pip install -r requirements.txt`. Start command:
`uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

Kept alive via an UptimeRobot monitor hitting `/health` every 5 minutes.

## Status

Working end to end: habit CRUD, daily checklist with instant save (no
reload), point scoring (instant for bad habits, nightly rollover for
good habits), reward shop with redemption tracking, Discord bot
(`/points`, `/rewards`, `/redeem`, bad-habit alerts, daily reports).

Not yet built: website login protection, point-history page,
habit reordering, notification timing as a setting.