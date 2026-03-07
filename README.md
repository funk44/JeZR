# JeZR

> An AI training coach in your WhatsApp. No app. No dashboard. No login.

---

## The idea

You finish a run. Your phone buzzes. A message breaks down how it went — pace against plan, HR, conditions, what it means for the week ahead. You don't open an app. You don't log into a dashboard. You just read it and get on with your day.

Every Sunday night, another message. Your week in review. Next week's training proposed. You reply YES. The plan uploads to Intervals.icu and syncs to Garmin. If you want to change something, you say so. JeZR revises and re-presents. Loop until you're happy, then YES.

That's it. Your entire coaching relationship happens in WhatsApp.

---

## What it looks like

**After a run:**

```
Solid 12km at 5:14 with avg HR 152 — right in the aerobic pocket and well
within the planned 5:10–5:20 window. Conditions were warm (27°C, 78% humidity)
so the slight HR elevation makes sense. Good execution.
```

**Sunday night:**

```
Week of 9 Mar

52km with good execution on Tuesday's tempo. Long run on Sunday was slower than
planned but 28°C and 81% humidity accounts for it. Wednesday's intervals were
skipped — worth picking up early next week if legs feel good.

─────────────────
PROPOSED NEXT WEEK

Mon 16 Mar — Rest
Tue 17 Mar — Tempo Run (11km)
  Warmup: 2km easy (82%)
  Main: 6km tempo (97%)
  Cooldown: 3km easy (82%)
Wed 18 Mar — Recovery Run (7km)
  35min easy (81%)
Thu 19 Mar — Rest
Fri 20 Mar — Intervals (10km)
  Warmup: 2km easy (82%)
  Main: 6x [1km @ 105% / 90s recovery]
  Cooldown: 2km easy (82%)
Sat 21 Mar — Rest
Sun 22 Mar — Long Run (22km)
  110min easy (82%)

─────────────────
Reply YES to upload to Intervals.icu, or tell me what to change.
```

You reply: *"Move the intervals to Thursday, I've got an early flight Friday"*

JeZR revises and sends the updated plan back. You reply YES.

---

## What's behind it

JeZR is built on a few convictions:

**The athlete stays in control.** JeZR proposes. You approve. Nothing reaches your calendar without your explicit sign-off. It will never auto-adjust your plan or make decisions on your behalf.

**Context beats data.** Knowing you ran 12km at 5:14 is less useful than knowing you ran 12km at 5:14 in 29°C humidity, the day after a hard Zwift session, two weeks out from your goal race. JeZR accumulates that context over time — your injury history, how you respond to heat, what your work schedule does to your training — and uses it every time it speaks to you.

**Honest feedback, not encouragement.** If you went out too hard, JeZR will say so. Generic encouragement is not useful.

**Consistency over cleverness.** The weekly loop is deliberately simple. Review, propose, approve, upload. Every week. No black box.

---

## What JeZR is not

- It is not an autonomous training AI. It does not adjust your plan without asking.
- It is not a generic fitness app. It knows who you are specifically.
- It is not a black box. Every proposed plan can be inspected, questioned, and rejected.
- It requires OpenClaw, an always-on device, and some setup investment. It is for athletes who want a tool that actually knows them.

---

## Requirements

- [Intervals.icu](https://intervals.icu) account with API access
- [OpenClaw](https://docs.openclaw.ai) running on an always-on device (thin client, NAS, Raspberry Pi)
- WhatsApp connected to OpenClaw
- Google Drive connected to OpenClaw (for weekly backups)
- [Anthropic API key](https://console.anthropic.com)
- Python 3.11+

---

## Installation

```bash
git clone https://github.com/funk44/jezr.git
cd jezr
pip install -e .
```

Copy the environment file and fill in your credentials:

```bash
cp .env.example .env
```

```
INTERVALS_API_KEY=          # from Intervals.icu → Settings → API
INTERVALS_ATHLETE_ID=       # your numeric athlete ID from Intervals.icu
CLAUDE_API_KEY=             # from console.anthropic.com
LOCAL_TIMEZONE=Australia/Melbourne
JEZR_NOTIFIER=openclaw
JEZR_OPENCLAW_DIR=~/.openclaw
JEZR_OPENCLAW_OUTBOX=~/.openclaw/outbox.txt
```

---

## First run

```bash
jezr setup
```

This walks you through two things:

**1. Athlete profile generation**

JeZR prints a prompt. Paste it into Claude, ChatGPT, or your AI of choice and answer the questions conversationally — think of it as telling a new coach everything they need to know about you. The richer your answers, the better the coaching.

The AI generates two files:
- `context/athlete.json` — structured variables: threshold pace, race targets, volume, FTP
- `context/athlete.md` — your narrative coaching context: injury history, how you respond to load, what your life looks like around training, what good feedback means to you

Save both to `context/`. Run `jezr profile` to confirm they loaded.

**Already have athlete context written somewhere else?**

```bash
jezr setup --import ~/path/to/existing-notes.md
```

Feed in a doc, a coach's notes, a previous AI conversation — anything. JeZR will restructure it into the two profile files and tell you what's missing.

**2. OpenClaw wiring**

After the profile step, `jezr setup` configures OpenClaw automatically — registers the Sunday night cron jobs, adds the poller keepalive to HEARTBEAT.md, and sets up the plan approval handler in AGENT.md. See [docs/openclaw.md](docs/openclaw.md) for details.

---

## Your athlete profile

The profile is what separates coaching from data retrieval.

`athlete.json` holds structured variables the code reads directly. `athlete.md` holds the narrative context injected into every AI call — the stuff a good coach carries in their head. Injury patterns, how you respond to heat, what happens to your training when work gets heavy, what a hard Zwift climb does to your legs for the next three days.

This document evolves. Add a race report after a key event. Note a pattern you've noticed. The richer it gets, the better the plans get.

```bash
jezr profile          # view current profile summary
```

JeZR warns you if the profile hasn't been reviewed in more than 90 days.

**Back it up.** JeZR backs up automatically to Google Drive every Sunday, but keeping a copy in a private repository is also worth doing. This file becomes more valuable over time.

---

## CLI reference

| Command | Description |
|---|---|
| `jezr setup` | First-run: athlete profile generation and OpenClaw wiring |
| `jezr setup --import <file>` | Import existing athlete notes and restructure into profile files |
| `jezr profile` | View athlete profile summary. Warns if overdue for review. |
| `jezr poll` | Start the activity poller. Runs until interrupted. |
| `jezr review` | Trigger weekly review manually |
| `jezr review --week-to-date` | Summarise current week against planned — no new plan |
| `jezr review --feedback "TEXT"` | Revise the pending plan based on your feedback |
| `jezr upload --planned <file>` | Validate and upload a plan JSON to Intervals.icu |
| `jezr validate --planned <file>` | Validate a plan JSON without uploading |
| `jezr backup` | Manually trigger a backup |
| `jezr log` | Show recent log entries. Options: `--n`, `--level`, `--source` |

---

## Plan validation

Every proposed plan goes through two stages before you see it:

**Schema validation** — hard check. Pace values must be integers, required fields must be present, structure must be valid. Schema failures block the plan entirely.

**AI sense check** — advisory. Claude reviews the plan for things schema validation can't catch: pace values that don't match session intent, volume spikes, back-to-back hard sessions, load that doesn't fit your stated block phase. Flags are shown as warnings alongside the plan — you decide whether to act on them.

---

## Pace conventions

Pace values in planned workouts are integers representing percentage of threshold pace. Set your threshold pace in Intervals.icu → Settings → Sport Settings → Run → Threshold Pace.

| Zone | % of threshold |
|---|---|
| Recovery | 65–70% |
| Easy / long run | 80–85% |
| Marathon pace | 88–92% |
| Tempo | 95–100% |
| Threshold | 100% |
| Intervals | 100–110% |
| Strides | 100–112% |

---

## Weekly backup

Every Sunday night JeZR backs up:
- `context/athlete.json` and `context/athlete.md`
- `data/jezr.db` — full history of planned and actual sessions
- `plans/` — archived approved plans

Backup is a dated zip pushed to Google Drive via OpenClaw. Local copies kept for 4 weeks (configurable via `JEZR_BACKUP_RETAIN_WEEKS`).

---

## OpenClaw integration

See [docs/openclaw.md](docs/openclaw.md) for full setup — cron job configuration, HEARTBEAT.md and AGENT.md wiring, SMB share access from Windows, and the Google Drive backup flow.

---

## Roadmap

**V1.5** — Full ride integration. Structured ride planning, cross-sport fatigue awareness, FTP-based ride workouts. Intervals.icu users skew heavily to cycling and triathlon — rides are a first-class concern, not an afterthought.

**V2** — Mid-week check-ins and athlete sentiment logging, mid-week plan adjustment on fatigue signals, configurable review schedule, Telegram and additional messaging channels, multi-provider AI support (OpenAI, Google), profile import from backup, longitudinal pattern analysis.

---

## Contributing

JeZR is open source. Issues and pull requests welcome.

Particularly interested in triathlon and cycling use cases ahead of v1.5. If you've adapted JeZR for your setup, open an issue and share what you've done.

---

## License

MIT