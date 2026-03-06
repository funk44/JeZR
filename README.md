# JeZR

An AI training coach that knows your history, watches every session, and proposes — never decides.

JeZR connects to Intervals.icu, stores your planned and completed sessions in a local database, and delivers immediate post-workout feedback and a weekly training review via WhatsApp. Every Sunday night it proposes next week's plan. You approve it. It uploads to Intervals.icu and syncs to Garmin.

It is built for endurance athletes who want data-driven coaching context without handing over control of their training to an algorithm.

---

## How it works

**After every session** — JeZR detects your completed run or ride on Intervals.icu, compares it to what was planned, factors in the weather, and sends you a WhatsApp message within minutes. Direct feedback from a coach who has your full context, not a generic notification from a fitness app.

**Every Sunday at 9pm** — JeZR reviews the week: what you planned, what you actually did, how conditions affected things. It proposes next week's training. You reply YES. It uploads the plan to Intervals.icu and it syncs to Garmin.

**If you want to change something** — reply with what you want adjusted. JeZR revises the plan and re-presents it. Loop until you're happy, then YES to upload.

---

## Requirements

- [Intervals.icu](https://intervals.icu) account with API access
- [OpenClaw](https://openclaw.io) running on a always-on device (thin client, NAS, Raspberry Pi)
- WhatsApp connected to OpenClaw
- Google Drive connected to OpenClaw (for weekly backups)
- Anthropic API key ([get one here](https://console.anthropic.com))
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
INTERVALS_API_KEY=        # from Intervals.icu → Settings → API
INTERVALS_ATHLETE_ID=     # your numeric athlete ID from Intervals.icu
CLAUDE_API_KEY=           # from console.anthropic.com
LOCAL_TIMEZONE=Australia/Melbourne
JEZR_NOTIFIER=openclaw
JEZR_OPENCLAW_DIR=~/openclaw
JEZR_OPENCLAW_OUTBOX=~/openclaw/outbox.txt
```

---

## First run

```bash
jezr setup
```

This will:

1. Print a prompt to generate your athlete profile — paste it into Claude, ChatGPT, or your AI of choice, answer the questions, and save the two output files to `context/`
2. Validate your profile files
3. Auto-configure OpenClaw — appends JeZR scheduling and approval blocks to your `HEARTBEAT.md` and `AGENT.md`

### Generating your athlete profile

`jezr setup` prints a prompt. Paste it into your AI and answer the questions conversationally — think of it as telling a new coach everything they need to know about you. The richer your answers, the more useful JeZR becomes.

The AI will output two files:
- `context/athlete.json` — structured variables (threshold pace, race targets, volume ranges)
- `context/athlete.md` — your narrative coaching context (injury history, how you respond to load, what good feedback looks like, life context)

Save both to the `context/` directory. Run `jezr profile` to confirm they loaded correctly.

**These files are never committed to git and never leave your machine except via your own Google Drive backup.**

---

## Athlete profile maintenance

Your athlete profile should be reviewed:
- At the start of each new training block
- After a major race (add a race report to `athlete.md`)
- After any significant injury or goal change
- When you notice a pattern worth capturing

```bash
jezr profile   # view current profile summary
```

JeZR will warn you if your profile hasn't been reviewed in more than 90 days.

**Back up your `athlete.md`** — it accumulates race reports, injury notes, and coaching insights over time. JeZR backs it up automatically to Google Drive every Sunday, but keeping a copy in a private repository is also worth doing.

---

## CLI reference

| Command | Description |
|---|---|
| `jezr setup` | First-run setup — athlete profile generation and OpenClaw wiring |
| `jezr profile` | View athlete profile summary. Warns if overdue for review. |
| `jezr poll` | Start the activity poller. Runs until interrupted. |
| `jezr review` | Trigger weekly review manually — sends WhatsApp with review and proposed plan |
| `jezr review --week-to-date` | Summarise the current week so far against planned. No new plan. |
| `jezr review --feedback "TEXT"` | Revise the pending plan based on your feedback |
| `jezr upload --planned <file>` | Validate and upload a plan JSON to Intervals.icu |
| `jezr validate --planned <file>` | Validate a plan JSON without uploading |
| `jezr backup` | Manually trigger a backup |

---

## Plan validation

Before any plan reaches Intervals.icu it goes through two stages:

**Schema validation** — hard check. Pace values must be integers, required fields must be present, structure must be valid. Schema failures block upload.

**AI sense check** — advisory. Claude reviews the proposed plan for things the schema can't catch: pace values that don't match session intent, volume spikes, back-to-back hard sessions, structure that doesn't fit your stated training phase. Sense check flags are shown as warnings — you decide whether to act on them.

---

## Planned workout schema

Plans are JSON arrays of workout objects. Pace values are integers representing percentage of threshold pace.

```json
[
  {
    "date": "2026-03-10",
    "all_day": true,
    "sport": "Run",
    "name": "Tempo Run",
    "sections": [
      {
        "name": "Warmup",
        "trainings": [
          { "duration": "2km", "pace": 82, "description": "Easy warmup" }
        ]
      },
      {
        "name": "Main set",
        "trainings": [
          { "duration": "6km", "pace": 97, "description": "Tempo — controlled effort" }
        ]
      },
      {
        "name": "Cooldown",
        "trainings": [
          { "duration": "2km", "pace": 82, "description": "Easy cooldown" }
        ]
      }
    ]
  }
]
```

See `context/sample_plan.json` for a full week example.

---

## Pace conventions

| Zone | % of threshold pace |
|---|---|
| Recovery | 65–70% |
| Easy | 80–85% |
| Marathon pace | 88–92% |
| Tempo | 95–100% |
| Threshold | 100% |
| Intervals | 100–110% |
| Strides | 100–112% |

Set your threshold pace in Intervals.icu → Settings → Sport Settings → Run → Threshold Pace.

---

## Weekly backup

Every Sunday night JeZR automatically backs up:
- `context/athlete.json`
- `context/athlete.md`
- `data/jezr.db`
- `plans/` archived plans

The backup is a dated zip file pushed to Google Drive via OpenClaw. Local copies are retained for 4 weeks (configurable via `JEZR_BACKUP_RETAIN_WEEKS`).

---

## OpenClaw integration

See [docs/openclaw.md](docs/openclaw.md) for full setup instructions including HEARTBEAT.md and AGENT.md configuration, SMB share access from Windows, and the Google Drive backup flow.

---

## Philosophy

JeZR is built on a few principles:

**The athlete stays in control.** JeZR proposes. You approve. Nothing reaches your calendar without your sign-off.

**Context beats data.** Knowing you ran 12km at 5:14 is less useful than knowing you ran 12km at 5:14 in 29°C humidity the day after a hard Zwift session, two weeks out from a goal race. JeZR accumulates that context over time.

**Consistency over cleverness.** The weekly loop — review, propose, approve, upload — is deliberately simple and repeatable. It does not auto-adjust your plan or make decisions on your behalf.

**Honest feedback.** Post-workout feedback is direct and data-driven. If you went out too hard, JeZR will say so. If the session was well-executed, it will say that too. Generic encouragement is not useful.

---

## Roadmap

**V1.5** — Full ride integration: structured ride planning, cross-sport fatigue awareness, FTP-based ride workouts alongside threshold-based run workouts.

**V2** — Mid-week check-ins and sentiment logging, mid-week plan adjustment based on fatigue signals, longitudinal pattern analysis.

---

## Contributing

JeZR is open source. Issues and pull requests welcome.

If you're building on JeZR or have adapted it for your own training setup, open an issue and share what you've done — particularly interested in triathlon and cycling use cases ahead of v1.5.

---

## License

MIT