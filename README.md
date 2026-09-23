# Psychopathology Training Bot

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

Then open `.env` in a text editor and fill in two required values: your
Anthropic API key from https://console.anthropic.com, and `DATABASE_URL`.
`.env` is git-ignored, so neither ends up in the repository.

Psychopathology Training Bot stores transcripts in Postgres rather than in a
local file, so they survive restarts and redeploys on hosts with an ephemeral
filesystem. For local development the quickest option is a free database from
[Neon](https://neon.tech): create a project and paste the connection string it
gives you into `DATABASE_URL`. A Postgres you run yourself works equally well.
The tables are created automatically on first start.

Start the server:

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

The `THERAPYBOT_` prefix predates the project's rename and is kept so that
existing deployments keep working without re-entering their secrets.

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — (required) | API key for the model |
| `THERAPYBOT_MODEL` | `claude-sonnet-5` | Claude model used for the patient. `claude-opus-5` is stronger and about 2.5x the price |
| `THERAPYBOT_ADMIN_PASSWORD` | `admin` | Password for the instructor area — **change this** |
| `THERAPYBOT_SECRET` | random per start | Flask session secret. **Required in production**: without it admin logins drop on restart and fail with more than one worker |
| `THERAPYBOT_ACCESS_CODE` | empty (no code) | Code students must enter to start a session. **Set this on any public URL**, otherwise anyone can spend your API credit |
| `THERAPYBOT_MAX_MESSAGES` | `40` | Maximum student messages per session (`0` = unlimited). Bounds the cost of one session |
| `DATABASE_URL` | — (required) | Postgres connection string where sessions and transcripts are stored |
| `THERAPYBOT_DB_POOL_SIZE` | `8` | Maximum database connections. Match it to the gunicorn `--threads` count |
| `PORT` | `5000` | HTTP port |

All of these can be set either in `.env` or as real environment variables.
The server logs a warning at startup for each production setting that is
still at its unsafe default.

## Deploying for a class (Render)

The app is a normal Flask service and runs anywhere Python runs. The included
[`render.yaml`](render.yaml) describes a setup on [Render](https://render.com)
that costs nothing: one web service on Render's Free compute plan, with
transcripts kept in a free Postgres database hosted elsewhere.

The database has to live outside Render for a reason worth understanding. A
free Render service has no persistent disk, and its filesystem is erased every
time it restarts **or spins down after 15 minutes without traffic**. Anything
written locally would disappear within the hour. An external database is not
affected by any of that.

### 1. Create the database

1. Sign up at [neon.tech](https://neon.tech) and create a project. Pick the
   region closest to your Render region (`eu-central-1` for Frankfurt) so the
   two are not talking across an ocean.
2. Copy the connection string. It looks like
   `postgresql://user:password@host/dbname?sslmode=require`. Use the **pooled**
   connection string if Neon offers you the choice.

Neon's free tier does not expire. Render's own free Postgres does expire 30
days after creation, so do not use that one for a course that runs longer.
Supabase also works; its free database pauses after a week of inactivity and
has to be resumed from their dashboard.

### 2. Deploy the web service

1. Push this repository to GitHub (or GitLab / Bitbucket).
2. In the Render dashboard choose **New → Blueprint** and select the
   repository. Render reads `render.yaml`.
3. Render asks for the four secrets marked `sync: false`: the database
   connection string, your Anthropic API key, the instructor password, and the
   student access code. `THERAPYBOT_SECRET` is generated automatically.
4. Click **Apply**. The first deploy takes a couple of minutes. The tables are
   created on first start. The service URL looks like
   `https://psychopathology-training-bot.onrender.com`; hand it to students
   together with the access code.
5. In the Anthropic console, set a **monthly spend limit** on the API key's
   workspace so a leaked URL or code cannot run up an open-ended bill.

### What the free plan costs you

- **The first request after a quiet spell is slow.** Render spins the service
  down after 15 minutes of inactivity and takes about a minute to wake it.
  Students who start a session at a random hour will wait; students working in
  a group will not notice after the first one.
- **750 instance hours per month per workspace.** A service only consumes them
  while awake, so intermittent class use stays well inside the limit, but the
  hours are shared with anything else you run free on Render.
- **Render may suspend a free service that makes heavy outbound API calls.**
  Calling the Anthropic API is this app's whole purpose. One class is unlikely
  to trip it, but there is no appeal other than moving to a paid plan, which is
  $7/month for the smallest instance.

If any of that becomes a problem, the fix is to change `plan: free` to
`plan: 0.5c-512mb` in `render.yaml` and redeploy. Nothing else changes, and the
database stays where it is.

To run under gunicorn on any other host, use the same command:
`gunicorn --workers 1 --threads 8 --timeout 120 app:app`.

### Sleeping databases

Neon suspends a free database after a few minutes without queries and drops
whatever connections were open. The app therefore keeps **no** idle database
connections: it opens one per request and closes it again, so there is never a
dead connection waiting to be handed out. Connection attempts are retried while
the database wakes, and if it still does not answer the student sees a short
"try again in a few seconds" message rather than an error page.

Render's health check polls `/`, which deliberately touches no database. That
keeps the web service warm without holding the database awake and burning free
compute hours.

If students ever do report an error, the server log names the cause on the
final line of the traceback. `PoolTimeout` means the database did not wake in
time, and raising `THERAPYBOT_DB_TIMEOUT` above its default of 30 seconds is
the fix.

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

Transcripts are safe from Render restarts, but a free database tier comes with
no backup guarantees. Download `export.json` after each course block so you
hold a copy that does not depend on anyone's free plan.

## How it works

- The student enters a name/ID, picks English or German, and starts a session.
- The server randomly picks one of the disorder cases in `cases.py` and a
  randomized persona (name, age, occupation), and instructs the model via a
  system prompt to role-play that patient. The assigned disorder never leaves
  the server until the diagnosis is submitted.
- Every message is stored in Postgres as it happens, so a session is recorded
  even if the student closes the tab without submitting a diagnosis.
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
