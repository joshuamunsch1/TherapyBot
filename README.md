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
on the same network can connect via `http://<your-ip>:5000`.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — (required) | API key for the model |
| `THERAPYBOT_MODEL` | `claude-opus-5` | Claude model used for the patient |
| `THERAPYBOT_ADMIN_PASSWORD` | `admin` | Password for the instructor area — **change this** |
| `THERAPYBOT_SECRET` | random per start | Flask session secret (set it to keep admin logins across restarts) |
| `PORT` | `5000` | HTTP port |

All of these can be set either in `.env` or as real environment variables.

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
