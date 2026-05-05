import os
from flask import Flask, request, jsonify, render_template_string
import anthropic

app = Flask(__name__)

# ---------------------------------------------------------------------------
# HTML template (single-file approach – no separate templates/ folder needed)
# ---------------------------------------------------------------------------
HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Claude Chat</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f0f2f5;
      display: flex;
      justify-content: center;
      align-items: flex-start;
      min-height: 100vh;
      padding: 40px 16px;
    }

    .container {
      width: 100%;
      max-width: 760px;
    }

    h1 {
      text-align: center;
      font-size: 1.6rem;
      color: #1a1a2e;
      margin-bottom: 28px;
      letter-spacing: -0.3px;
    }

    .chat-box {
      background: #fff;
      border-radius: 16px;
      box-shadow: 0 4px 24px rgba(0,0,0,0.08);
      padding: 28px;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }

    #history {
      display: flex;
      flex-direction: column;
      gap: 14px;
      max-height: 500px;
      overflow-y: auto;
      padding-right: 4px;
    }

    .bubble {
      padding: 12px 16px;
      border-radius: 12px;
      line-height: 1.6;
      font-size: 0.95rem;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .bubble.user {
      background: #e8f0fe;
      color: #1a1a2e;
      align-self: flex-end;
      max-width: 80%;
      border-bottom-right-radius: 4px;
    }

    .bubble.assistant {
      background: #f6f6f6;
      color: #222;
      align-self: flex-start;
      max-width: 90%;
      border-bottom-left-radius: 4px;
    }

    .bubble .label {
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.5px;
      text-transform: uppercase;
      color: #888;
      margin-bottom: 4px;
    }

    .input-row {
      display: flex;
      gap: 10px;
      align-items: flex-end;
    }

    textarea {
      flex: 1;
      resize: none;
      border: 1.5px solid #d0d5dd;
      border-radius: 10px;
      padding: 10px 14px;
      font-size: 0.95rem;
      font-family: inherit;
      line-height: 1.5;
      min-height: 52px;
      max-height: 180px;
      outline: none;
      transition: border-color 0.2s;
      overflow-y: auto;
    }

    textarea:focus { border-color: #6c63ff; }

    button {
      background: #6c63ff;
      color: #fff;
      border: none;
      border-radius: 10px;
      padding: 13px 22px;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.2s, opacity 0.2s;
      white-space: nowrap;
    }

    button:hover:not(:disabled) { background: #574fd6; }
    button:disabled { opacity: 0.55; cursor: not-allowed; }

    .status {
      font-size: 0.82rem;
      color: #888;
      text-align: center;
      min-height: 18px;
    }

    .error { color: #c0392b; }
  </style>
</head>
<body>
  <div class="container">
    <h1>💬 Claude Chat</h1>
    <div class="chat-box">
      <div id="history"></div>
      <div class="input-row">
        <textarea id="prompt" placeholder="Type your message…" rows="2"></textarea>
        <button id="send-btn" onclick="sendMessage()">Send</button>
      </div>
      <p class="status" id="status"></p>
    </div>
  </div>

  <script>
    const history = [];   // [{role, content}, ...]

    const promptEl  = document.getElementById("prompt");
    const sendBtn   = document.getElementById("send-btn");
    const statusEl  = document.getElementById("status");
    const historyEl = document.getElementById("history");

    // Auto-resize textarea
    promptEl.addEventListener("input", () => {
      promptEl.style.height = "auto";
      promptEl.style.height = Math.min(promptEl.scrollHeight, 180) + "px";
    });

    // Send on Ctrl+Enter / Cmd+Enter
    promptEl.addEventListener("keydown", e => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") sendMessage();
    });

    function appendBubble(role, text) {
      const wrap = document.createElement("div");
      wrap.className = `bubble ${role}`;
      const label = document.createElement("div");
      label.className = "label";
      label.textContent = role === "user" ? "You" : "Claude";
      wrap.appendChild(label);
      const body = document.createElement("div");
      body.textContent = text;
      wrap.appendChild(body);
      historyEl.appendChild(wrap);
      historyEl.scrollTop = historyEl.scrollHeight;
    }

    async function sendMessage() {
      const text = promptEl.value.trim();
      if (!text) return;

      // Show user bubble
      appendBubble("user", text);
      history.push({ role: "user", content: text });

      promptEl.value = "";
      promptEl.style.height = "auto";
      sendBtn.disabled = true;
      statusEl.textContent = "Claude is thinking…";
      statusEl.classList.remove("error");

      try {
        const res = await fetch("/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages: history })
        });

        const data = await res.json();

        if (!res.ok) {
          throw new Error(data.error || "Unknown error");
        }

        appendBubble("assistant", data.reply);
        history.push({ role: "assistant", content: data.reply });
        statusEl.textContent = "";

      } catch (err) {
        statusEl.textContent = "Error: " + err.message;
        statusEl.classList.add("error");
        // Remove the last user message from history on failure
        history.pop();
      } finally {
        sendBtn.disabled = false;
        promptEl.focus();
      }
    }
  </script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    messages = data.get("messages", [])

    if not messages:
        return jsonify({"error": "No messages provided."}), 400

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY environment variable is not set."}), 500

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8096,
            messages=messages,
        )
        reply = response.content[0].text
        return jsonify({"reply": reply})

    except anthropic.APIStatusError as e:
        return jsonify({"error": f"Anthropic API error: {e.message}"}), e.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting Claude Chat on http://localhost:{port}")
    print("Make sure ANTHROPIC_API_KEY is set in your environment.")
    app.run(host="0.0.0.0", port=port, debug=False)
