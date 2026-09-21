import os
import csv
import io
import json
import secrets
from functools import wraps

import anthropic
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session as flask_session,
    url_for,
)

import cases
import db

# Load settings from a local .env file if present, so the API key does not have
# to be set in the shell on every start. Real environment variables win.
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("THERAPYBOT_SECRET", secrets.token_hex(32))

MODEL = os.environ.get("THERAPYBOT_MODEL", "claude-opus-5")
ADMIN_PASSWORD = os.environ.get("THERAPYBOT_ADMIN_PASSWORD", "admin")
MAX_MESSAGE_CHARS = 2000

# Created lazily so the server can start (and show a clear error) without a key.
_client = None


def get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


db.init_db()

# UI strings for the session page, keyed by session language.
STRINGS = {
    "en": {
        "you": "You (therapist)",
        "start_hint": "The patient has entered the room. Open the conversation.",
        "placeholder": "Say something to the patient… (Ctrl+Enter to send)",
        "send": "Send",
        "thinking": "The patient is responding…",
        "finish": "Finish session & diagnose",
        "diagnosis_title": "Your diagnosis",
        "diagnosis_pick": "— select a diagnosis —",
        "justification_label": "Justification (optional): which symptoms point to this diagnosis?",
        "submit_diagnosis": "Submit diagnosis",
        "correct": "Correct!",
        "incorrect": "Not quite.",
        "actual_was": "The simulated patient had:",
        "back_home": "Start a new session",
        "patient_info": "Patient",
        "years_old": "years old",
    },
    "de": {
        "you": "Sie (Therapeut:in)",
        "start_hint": "Die Patientin / der Patient ist eingetreten. Eröffnen Sie das Gespräch.",
        "placeholder": "Sagen Sie etwas… (Ctrl+Enter zum Senden)",
        "send": "Senden",
        "thinking": "Antwort wird geschrieben…",
        "finish": "Sitzung beenden & Diagnose stellen",
        "diagnosis_title": "Ihre Diagnose",
        "diagnosis_pick": "— Diagnose wählen —",
        "justification_label": "Begründung (optional): Welche Symptome sprechen für diese Diagnose?",
        "submit_diagnosis": "Diagnose einreichen",
        "correct": "Richtig!",
        "incorrect": "Leider nicht richtig.",
        "actual_was": "Die simulierte Patientin / der simulierte Patient hatte:",
        "back_home": "Neue Sitzung starten",
        "patient_info": "Patient:in",
        "years_old": "Jahre alt",
    },
}


# ---------------------------------------------------------------------------
# Student-facing routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/session", methods=["POST"])
def create_session():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    language = data.get("language")
    if not name:
        return jsonify({"error": "Please enter your name or student ID."}), 400
    if language not in ("en", "de"):
        return jsonify({"error": "Invalid language."}), 400

    case = cases.pick_case()
    persona = cases.make_persona(case)
    session_id = db.create_session(name, language, case["id"], persona)
    return jsonify({"session_id": session_id})


@app.route("/session/<session_id>")
def session_page(session_id):
    session = db.get_session(session_id)
    if session is None:
        return redirect(url_for("index"))

    language = session["language"]
    persona = session["persona"]
    strings = STRINGS[language]
    occupation = persona["occupation_de"] if language == "de" else persona["occupation_en"]

    finished = session["diagnosis_guess"] is not None
    feedback = None
    if finished:
        feedback = _feedback_payload(session)

    config = {
        "sessionId": session_id,
        "patientName": persona["name"],
        "strings": strings,
        "options": cases.diagnosis_options(language),
        "messages": db.get_messages(session_id),
        "finished": finished,
        "feedback": feedback,
    }
    return render_template(
        "session.html",
        strings=strings,
        persona=persona,
        occupation=occupation,
        config_json=json.dumps(config).replace("<", "\\u003c"),
    )


@app.route("/api/session/<session_id>/message", methods=["POST"])
def send_message(session_id):
    session = db.get_session(session_id)
    if session is None:
        return jsonify({"error": "Unknown session."}), 404
    if session["diagnosis_guess"] is not None:
        return jsonify({"error": "This session is finished."}), 409

    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Empty message."}), 400
    if len(text) > MAX_MESSAGE_CHARS:
        return jsonify({"error": f"Message too long (max {MAX_MESSAGE_CHARS} characters)."}), 400

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return jsonify({"error": "Server is missing ANTHROPIC_API_KEY — set it and restart."}), 500

    case = cases.CASES_BY_ID[session["disorder_id"]]
    system_prompt = cases.build_system_prompt(case, session["persona"], session["language"])
    history = [
        {"role": m["role"], "content": m["content"]} for m in db.get_messages(session_id)
    ]
    history.append({"role": "user", "content": text})

    try:
        response = get_client().messages.create(
            model=MODEL,
            # Roomy ceiling: replies run ~200 tokens, but internal reasoning
            # shares this budget. Unused tokens are not billed.
            max_tokens=2048,
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=history,
        )
    except anthropic.RateLimitError:
        return jsonify({"error": "Rate limited by the API — wait a moment and try again."}), 429
    except anthropic.AuthenticationError:
        return jsonify({"error": "The API key was rejected. Check ANTHROPIC_API_KEY on the server."}), 500
    except anthropic.APIStatusError as e:
        return jsonify({"error": f"API error: {e.message}"}), 502
    except anthropic.APIConnectionError:
        return jsonify({"error": "Could not reach the Anthropic API. Check the internet connection."}), 502
    except anthropic.AnthropicError as e:
        # e.g. client construction failed because no API key is configured
        if "api_key" in str(e).lower():
            return jsonify({"error": "Server is missing ANTHROPIC_API_KEY."}), 500
        return jsonify({"error": f"API client error: {e}"}), 500

    reply = next((b.text for b in response.content if b.type == "text"), "")
    if not reply:
        return jsonify({"error": "The model returned an empty reply. Please try again."}), 502

    # Persist only after a successful API call so a failed attempt leaves no residue.
    db.add_message(session_id, "user", text)
    db.add_message(session_id, "assistant", reply)
    return jsonify({"reply": reply})


@app.route("/api/session/<session_id>/diagnosis", methods=["POST"])
def submit_diagnosis(session_id):
    session = db.get_session(session_id)
    if session is None:
        return jsonify({"error": "Unknown session."}), 404
    if session["diagnosis_guess"] is not None:
        return jsonify({"error": "Diagnosis already submitted."}), 409

    data = request.get_json(force=True)
    guess = data.get("guess")
    justification = (data.get("justification") or "").strip()
    valid_ids = {o["id"] for o in cases.diagnosis_options(session["language"])}
    if guess not in valid_ids:
        return jsonify({"error": "Please select a diagnosis."}), 400

    correct = guess == session["disorder_id"]
    db.record_diagnosis(session_id, guess, correct, justification)

    session = db.get_session(session_id)
    return jsonify(_feedback_payload(session))


def _feedback_payload(session):
    language = session["language"]
    case = cases.CASES_BY_ID[session["disorder_id"]]
    return {
        "correct": bool(session["diagnosis_correct"]),
        "guess_label": cases.diagnosis_label(session["diagnosis_guess"], language),
        "actual_label": cases.diagnosis_label(session["disorder_id"], language),
        "explanation": case["feedback_de"] if language == "de" else case["feedback_en"],
    }


# ---------------------------------------------------------------------------
# Instructor routes
# ---------------------------------------------------------------------------

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not flask_session.get("admin"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("password", ""), ADMIN_PASSWORD):
            flask_session["admin"] = True
            return redirect(url_for("admin"))
        error = "Wrong password."
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    flask_session.pop("admin", None)
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin():
    sessions = db.list_sessions()
    for s in sessions:
        s["disorder_label"] = cases.diagnosis_label(s["disorder_id"], "en")
        s["guess_label"] = (
            cases.diagnosis_label(s["diagnosis_guess"], "en") if s["diagnosis_guess"] else None
        )
    return render_template("admin.html", sessions=sessions)


@app.route("/admin/session/<session_id>")
@admin_required
def admin_session(session_id):
    session = db.get_session(session_id)
    if session is None:
        return redirect(url_for("admin"))
    session["disorder_label"] = cases.diagnosis_label(session["disorder_id"], "en")
    session["guess_label"] = (
        cases.diagnosis_label(session["diagnosis_guess"], "en") if session["diagnosis_guess"] else None
    )
    messages = db.get_messages(session_id)
    return render_template("admin_session.html", session=session, messages=messages)


@app.route("/admin/export.csv")
@admin_required
def export_csv():
    sessions = db.list_sessions()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "session_id", "student", "started_at", "language", "disorder",
        "guess", "correct", "justification", "diagnosed_at", "message_count",
    ])
    for s in sessions:
        writer.writerow([
            s["id"], s["student_name"], s["started_at"], s["language"],
            s["disorder_id"], s["diagnosis_guess"] or "",
            "" if s["diagnosis_correct"] is None else s["diagnosis_correct"],
            s["justification"] or "", s["diagnosed_at"] or "", s["message_count"],
        ])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=therapybot_sessions.csv"},
    )


@app.route("/admin/export.json")
@admin_required
def export_json():
    return Response(
        json.dumps(db.full_export(), indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=therapybot_sessions.json"},
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"TherapyBot running on http://localhost:{port}  (admin: /admin)")
    print("Make sure ANTHROPIC_API_KEY is set in your environment.")
    app.run(host="0.0.0.0", port=port, debug=False)
