# TherapyBot

A training tool for psychology students: the student holds a pseudo therapy
session with an AI-simulated patient that has been randomly assigned one of
several psychological disorders, then submits a diagnosis and receives
immediate feedback. Every conversation is saved for later analysis by the
instructor.

## Setup

```
python -m venv venv
venv\Scripts\activate        # Windows  (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and put your Anthropic API key in it:

```
copy .env.example .env       # Windows  (Linux/macOS: cp .env.example .env)
```

Then open `.env` in a text editor and replace the placeholder key with your real
one from https://console.anthropic.com. `.env` is git-ignored, so the key never
gets committed. Start the server:

```
python app.py
```

If you prefer not to use a `.env` file, a normal environment variable works too
and takes precedence over it:

```
$env:ANTHROPIC_API_KEY="sk-ant-..."     # PowerShell, current session only
setx ANTHROPIC_API_KEY "sk-ant-..."     # persists, but open a new terminal after
```

Open http://localhost:5000. The server binds to `0.0.0.0`, so other devices
on the same network can connect via `http://<your-ip>:5000`. This is enough
for a single supervised classroom session; for homework use across a course,
see "Deploying for a class" below.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — (required) | API key for the model |
| `THERAPYBOT_MODEL` | `claude-opus-5` | Claude model used for the patient |
| `THERAPYBOT_ADMIN_PASSWORD` | `admin` | Password for the instructor area — **change this** |
| `THERAPYBOT_SECRET` | random per start | Flask session secret. **Required in production**: without it admin logins drop on restart and fail with more than one worker |
| `THERAPYBOT_ACCESS_CODE` | empty (no code) | Code students must enter to start a session. **Set this on any public URL**, otherwise anyone can spend your API credit |
| `THERAPYBOT_MAX_MESSAGES` | `40` | Maximum student messages per session (`0` = unlimited). Bounds the cost of one session |
| `THERAPYBOT_DB_PATH` | `sessions.db` next to `app.py` | Where the SQLite file lives. On a host with an ephemeral filesystem, point it at a persistent disk |
| `PORT` | `5000` | HTTP port |

All of these can be set either in `.env` or as real environment variables.
The server logs a warning at startup for each production setting that is
still at its unsafe default.

## Deploying for a class (Render)

The app is a normal Flask service and runs anywhere Python runs. The included
[`render.yaml`](render.yaml) describes a ready-made setup on
[Render](https://render.com): one web service under gunicorn, a 1 GB
persistent disk for the transcript database, and the environment variables
above. Steps:

1. Push this repository to GitHub (or GitLab / Bitbucket).
2. In the Render dashboard choose **New → Blueprint** and select the
   repository. Render reads `render.yaml`.
3. Render asks for the three secrets marked `sync: false`: your Anthropic API
   key, the instructor password, and the student access code. Fill them in.
   `THERAPYBOT_SECRET` is generated automatically.
4. Click **Apply**. The first deploy takes a couple of minutes. The service URL
   looks like `https://therapybot.onrender.com`; hand it to students together
   with the access code.
5. In the Anthropic console, set a **monthly spend limit** on the API key's
   workspace so a leaked URL or code cannot run up an open-ended bill.

Notes:

- The Starter plan is required: the free plan sleeps after idle (students would
  wait a minute for the first page) and cannot mount a persistent disk.
- With a disk attached, Render runs a single instance and deploys involve a
  short restart. That is fine for this workload.
- Transcripts live on the disk at `/var/data/sessions.db` and survive deploys
  and restarts. Render takes daily disk snapshots; on top of that, download
  `export.json` from the instructor area after each course block so you have an
  off-platform copy.
- To run under gunicorn on any other host use the same command:
  `gunicorn --workers 2 --threads 8 --timeout 120 app:app`.

## Reviewing transcripts

Every message is written to the database as it is sent, so a session is
recorded even if the student never submits a diagnosis. In the instructor area
you can:

- open any session and read it in the browser,
- download a single session as a plain-text file (`download as .txt` on the
  transcript page) for annotation or sharing with a reviewer,
- download `export.csv` (one row per session: student, disorder, guess,
  correct/incorrect, justification, message count) for spreadsheets,
- download `export.json` (every session with its full transcript) for archiving
  or analysis scripts.

## How it works

- The student enters a name/ID, picks English or German, and starts a session.
- The server randomly picks one of the disorder cases in `cases.py` and a
  randomized persona (name, age, occupation), and instructs the model via a
  system prompt to role-play that patient. The assigned disorder never leaves
  the server until the diagnosis is submitted.
- Every message is stored in `sessions.db` (SQLite) as it happens.
- After submitting a diagnosis the student sees correct/incorrect, the true
  disorder, and a hand-written explanation of the key diagnostic pointers.

## Instructor area

Go to `/admin` and log in with the admin password. You can:

- see all sessions (student, disorder, guess, correct/incorrect, message count),
- read full transcripts,
- download `export.csv` (one row per session) or `export.json` (full transcripts).

## Editing the cases

Everything clinical lives in [`cases.py`](cases.py):

- `CASES` — the disorder pool. Each entry has labels (EN/DE), a typical age
  range, a `symptom_brief` (instructions to the model on how the disorder
  presents, what to volunteer vs. reveal only on good questioning), and
  hand-authored feedback texts (EN/DE).
- `DISTRACTOR_DIAGNOSES` — extra options in the diagnosis dropdown that are
  never the answer.
- Persona pools (`FIRST_NAMES`, `OCCUPATIONS`, `LIVING_SITUATIONS`) — combined
  randomly so students can't recognize a disorder by its persona.
- `build_system_prompt` — the role-play instructions.

Adding a new disorder = adding one dict to `CASES`. No other code changes needed.

## Note

This is a teaching simulation, not clinical training, therapy, or medical
advice. The patient bot is instructed to break character if a student appears
to be in genuine personal distress and to point them to real support.
