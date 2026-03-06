# OpenClaw Integration Guide

OpenClaw is the scheduling and messaging layer that JeZR runs on top of. It handles:

- **Scheduling** — running `jezr review` every Sunday night and keeping the poller alive
- **WhatsApp I/O** — delivering post-workout feedback and weekly reviews to your phone, and routing your replies back to JeZR
- **Google Drive backup** — picking up backup zips from `JEZR_BACKUP_DIR` and pushing them to Google Drive

JeZR is designed to run standalone (stdout mode) or with OpenClaw (WhatsApp mode). This guide covers the OpenClaw setup.

---

## Prerequisites

Before wiring JeZR into OpenClaw, ensure:

1. **OpenClaw is installed and running** — see the OpenClaw documentation for installation
2. **WhatsApp is connected** — OpenClaw must have an active WhatsApp session
3. **Google Drive is connected** — for backup uploads (optional but recommended)
4. **JeZR is installed** — `pip install -e .` in the JeZR directory, `jezr --help` works
5. **`.env` is configured** — all required env vars set (see `.env.example`)

---

## Automatic setup via `jezr setup`

The easiest way to configure OpenClaw is to run `jezr setup`. After completing the athlete profile step, it will prompt:

```
Do you want to configure OpenClaw integration now? (yes/no):
```

If you say yes, it will:

1. Read `JEZR_OPENCLAW_DIR` from your environment, or prompt you for the path
2. Verify the directory contains `HEARTBEAT.md` and `AGENT.md`
3. Check whether JeZR blocks are already present (safe to re-run)
4. Append the JeZR scheduling and approval blocks to each file
5. Confirm what was updated

Set `JEZR_NOTIFIER=openclaw` and `JEZR_OPENCLAW_OUTBOX=<path>` in your `.env` to enable WhatsApp delivery.

---

## Manual setup

If you prefer to configure OpenClaw by hand, add the following blocks to your config files.

### HEARTBEAT.md

Append this block to your OpenClaw `HEARTBEAT.md`:

```markdown
# JeZR
## Weekly review and backup (Sunday 9pm)
- schedule: every Sunday at 21:00
- run: jezr review
- run: jezr backup

## Poller keepalive (every 5 minutes)
- schedule: every 5 minutes
- check_process: jezr poll
- start_if_stopped: jezr poll
```

This schedules the weekly review and backup for Sunday at 9pm, and ensures the poller restarts automatically after a reboot or crash.

### AGENT.md

Append this block to your OpenClaw `AGENT.md`:

```markdown
# JeZR
## Training plan approval
If the user sends a message that is exactly "YES" after receiving a training plan:
- run: jezr upload --planned data/pending_plan.json
- reply with the result

If the user sends any other reply after receiving a training plan:
- run: jezr review --feedback "{message}"
- send the revised plan for approval
```

This enables the plan approval loop: reply YES to upload, or send any other text to revise the plan.

---

## Accessing OpenClaw config files from Windows

If OpenClaw runs on a separate thin client (e.g. a Raspberry Pi or Linux box), you can edit its config files from Windows via SMB share.

**On the thin client**, enable SMB sharing for the OpenClaw directory:

```bash
# Install Samba if not already installed
sudo apt install samba

# Add to /etc/samba/smb.conf:
[openclaw]
   path = /home/youruser/openclaw
   read only = no
   browsable = yes
```

**On Windows**, map the share:

- Open File Explorer → right-click "This PC" → "Map network drive"
- Enter `\\<thin-client-ip>\openclaw`
- Or from PowerShell: `net use Z: \\<thin-client-ip>\openclaw`

You can then edit `HEARTBEAT.md` and `AGENT.md` directly in VSCode:

```
code \\<thin-client-ip>\openclaw\HEARTBEAT.md
```

---

## Google Drive backup

JeZR writes backup zips to `JEZR_BACKUP_DIR` (default: `./backups/`). OpenClaw monitors this directory using its Google Drive skill and uploads new zips automatically.

**No Google API credentials are needed in JeZR** — OpenClaw owns the Google auth.

To trigger a manual backup:

```bash
jezr backup
```

Zips are named `jezr_backup_YYYY-MM-DD.zip` and contain:
- `context/athlete.json`
- `context/athlete.md` (if it exists)
- `data/jezr.db`
- `plans/` directory contents

Local backups older than `JEZR_BACKUP_RETAIN_WEEKS` weeks (default: 4) are pruned automatically. Google Drive retains everything.

---

## Approval flow walkthrough

Here is what happens from Sunday night through to plan upload:

1. **Sunday 9pm** — OpenClaw triggers `jezr review`
2. JeZR queries the previous week's planned and actual sessions from SQLite
3. JeZR sends the week summary + proposed next week plan to Claude
4. Claude returns a written review and a proposed plan as JSON
5. JeZR validates the plan (schema check + AI sense check)
6. JeZR sends the WhatsApp message: review text, proposed plan in plain English, any flags, and "Reply YES to upload"
7. **Athlete replies YES** → OpenClaw triggers `jezr upload --planned data/pending_plan.json`
8. JeZR validates, uploads to Intervals.icu, stores IDs in SQLite, archives the plan
9. OpenClaw sends a confirmation message with the upload result
10. **Athlete replies with changes** → OpenClaw triggers `jezr review --feedback "<message>"`
11. JeZR passes the feedback to Claude with the current pending plan, gets a revised plan
12. JeZR sends the revised plan for re-approval — loop repeats until YES or cancel

---

## Troubleshooting

### Poller not starting

Check that `jezr poll` works from the command line:

```bash
jezr poll --debug
```

If it exits immediately, check:
- `.env` is present and `INTERVALS_API_KEY`, `INTERVALS_ATHLETE_ID`, `CLAUDE_API_KEY` are set
- `jezr` is on PATH (check with `which jezr`)
- The `check_process` / `start_if_stopped` directives in HEARTBEAT.md use the correct path

### WhatsApp messages not arriving

1. Check `JEZR_NOTIFIER=openclaw` is set in `.env`
2. Check `JEZR_OPENCLAW_OUTBOX` points to the correct outbox file
3. Verify OpenClaw is running and its WhatsApp session is active
4. Test the outbox manually: append a line to the outbox file and check if it arrives on WhatsApp

### Weekly review not firing

1. Check the HEARTBEAT.md block is correctly formatted and uses the right `jezr` path
2. Verify OpenClaw's scheduler is running
3. Trigger manually: `jezr review --debug`

### Backup not uploading to Google Drive

1. Check `JEZR_BACKUP_DIR` is set to a directory OpenClaw monitors
2. Verify OpenClaw's Google Drive skill is configured and authenticated
3. Trigger manually: `jezr backup --debug`
4. Check the `./backups/` directory for the zip file

### Plan approval loop not working

If "YES" does not trigger an upload:
1. Check the AGENT.md block is present and correctly formatted
2. Verify OpenClaw is processing inbound WhatsApp messages
3. Check that `data/pending_plan.json` exists (written by `jezr review`)
4. Upload manually: `jezr upload --planned data/pending_plan.json`

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `JEZR_NOTIFIER` | `stdout` | Set to `openclaw` to enable WhatsApp delivery |
| `JEZR_OPENCLAW_DIR` | — | Path to OpenClaw directory (used by `jezr setup`) |
| `JEZR_OPENCLAW_OUTBOX` | — | Path to OpenClaw outbox file for WhatsApp messages |
| `JEZR_BACKUP_DIR` | `./backups` | Directory to write backup zips |
| `JEZR_BACKUP_RETAIN_WEEKS` | `4` | Number of weeks of local backups to retain |
