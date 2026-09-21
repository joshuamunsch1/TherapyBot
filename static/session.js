const config = JSON.parse(document.getElementById("session-config").textContent);
const S = config.strings;

const historyEl = document.getElementById("history");
const promptEl = document.getElementById("prompt");
const sendBtn = document.getElementById("send");
const statusEl = document.getElementById("status");
const finishBtn = document.getElementById("finish");
const chatControls = document.getElementById("chat-controls");
const diagnosisPanel = document.getElementById("diagnosis-panel");
const diagnosisSelect = document.getElementById("diagnosis-select");
const diagnosisError = document.getElementById("diagnosis-error");
const feedbackPanel = document.getElementById("feedback-panel");
const remainingEl = document.getElementById("remaining");

let hintEl = null;
let remaining = config.maxUserMessages
  ? Math.max(0, config.maxUserMessages - config.userMessagesUsed)
  : null;

function updateRemaining() {
  if (remaining === null) return;
  remainingEl.textContent = S.remaining.replace("{n}", remaining);
  remainingEl.classList.toggle("low", remaining <= 5);
  if (remaining <= 0) lockInput(S.limit_reached);
}

// Called when the cap is hit: no more messages, only the diagnosis remains.
function lockInput(message) {
  promptEl.disabled = true;
  sendBtn.disabled = true;
  setStatus(message, false);
  showDiagnosisPanel();
}

function appendBubble(role, text) {
  if (hintEl) { hintEl.remove(); hintEl = null; }
  const wrap = document.createElement("div");
  wrap.className = `bubble ${role}`;
  const label = document.createElement("div");
  label.className = "label";
  label.textContent = role === "user" ? S.you : config.patientName;
  wrap.appendChild(label);
  const body = document.createElement("div");
  body.textContent = text;
  wrap.appendChild(body);
  historyEl.appendChild(wrap);
  historyEl.scrollTop = historyEl.scrollHeight;
}

function showHint() {
  hintEl = document.createElement("div");
  hintEl.className = "hint";
  hintEl.textContent = S.start_hint;
  historyEl.appendChild(hintEl);
}

function setStatus(text, isError) {
  statusEl.textContent = text || "";
  statusEl.classList.toggle("error", !!isError);
}

async function sendMessage() {
  const text = promptEl.value.trim();
  if (!text) return;

  appendBubble("user", text);
  promptEl.value = "";
  promptEl.style.height = "auto";
  sendBtn.disabled = true;
  finishBtn.disabled = true;
  setStatus(S.thinking);

  try {
    const res = await fetch(`/api/session/${config.sessionId}/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();
    if (!res.ok) {
      if (data.limit_reached) {
        // The server did not store this message; drop the bubble we drew optimistically.
        historyEl.lastElementChild?.remove();
        remaining = 0;
        updateRemaining();
        return;
      }
      throw new Error(data.error || "Unknown error");
    }
    appendBubble("assistant", data.reply);
    setStatus("");
    if (data.remaining !== null && data.remaining !== undefined) {
      remaining = data.remaining;
      updateRemaining();
    }
  } catch (err) {
    setStatus("Error: " + err.message, true);
    promptEl.value = text; // let the student retry without retyping
  } finally {
    finishBtn.disabled = false;
    if (remaining === null || remaining > 0) {
      sendBtn.disabled = false;
      promptEl.focus();
    }
  }
}

function showDiagnosisPanel() {
  diagnosisPanel.classList.remove("hidden");
  diagnosisPanel.scrollIntoView({ behavior: "smooth" });
}

function showFeedback(feedback) {
  chatControls.classList.add("hidden");
  diagnosisPanel.classList.add("hidden");
  feedbackPanel.classList.remove("hidden");

  const banner = document.getElementById("feedback-banner");
  banner.textContent = feedback.correct ? S.correct : S.incorrect;
  banner.classList.add(feedback.correct ? "correct" : "incorrect");

  document.getElementById("feedback-actual").textContent =
    `${S.actual_was} ${feedback.actual_label}`;
  document.getElementById("feedback-explanation").textContent = feedback.explanation;
  feedbackPanel.scrollIntoView({ behavior: "smooth" });
}

async function submitDiagnosis() {
  const guess = diagnosisSelect.value;
  if (!guess) {
    diagnosisError.textContent = S.diagnosis_pick;
    diagnosisError.classList.remove("hidden");
    return;
  }
  diagnosisError.classList.add("hidden");
  document.getElementById("submit-diagnosis").disabled = true;

  try {
    const res = await fetch(`/api/session/${config.sessionId}/diagnosis`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        guess,
        justification: document.getElementById("justification").value.trim(),
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Unknown error");
    showFeedback(data);
  } catch (err) {
    diagnosisError.textContent = err.message;
    diagnosisError.classList.remove("hidden");
    document.getElementById("submit-diagnosis").disabled = false;
  }
}

// --- wiring ---------------------------------------------------------------

promptEl.addEventListener("input", () => {
  promptEl.style.height = "auto";
  promptEl.style.height = Math.min(promptEl.scrollHeight, 180) + "px";
});
promptEl.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") sendMessage();
});
sendBtn.addEventListener("click", sendMessage);
finishBtn.addEventListener("click", showDiagnosisPanel);
document.getElementById("submit-diagnosis").addEventListener("click", submitDiagnosis);

// populate diagnosis dropdown
const placeholder = document.createElement("option");
placeholder.value = "";
placeholder.textContent = S.diagnosis_pick;
diagnosisSelect.appendChild(placeholder);
for (const opt of config.options) {
  const el = document.createElement("option");
  el.value = opt.id;
  el.textContent = opt.label;
  diagnosisSelect.appendChild(el);
}

// restore state (page reload / finished session)
if (config.messages.length === 0) {
  showHint();
} else {
  for (const m of config.messages) appendBubble(m.role, m.content);
}
if (config.finished && config.feedback) {
  showFeedback(config.feedback);
} else {
  updateRemaining();
  if (remaining === null || remaining > 0) promptEl.focus();
}
