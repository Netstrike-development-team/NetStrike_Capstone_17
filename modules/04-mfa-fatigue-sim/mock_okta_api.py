from flask import Flask, request, jsonify
import json
import os
from datetime import datetime

from config import API_PORT, APPROVAL_THRESHOLD, LOG_FILE

app = Flask(__name__)

push_counts = {}
human_decision = {}  # stores whether human approved or denied


#Log helper#
def save_log_entry(entry: dict):
    os.makedirs("logs", exist_ok=True)
    existing = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = []
    existing.append(entry)
    with open(LOG_FILE, "w") as f:
        json.dump(existing, f, indent=2)

#Login#
@app.route("/", methods=["GET"])
def login():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>SimCorp Login</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }

            body {
                font-family: Arial, sans-serif;
                background: #f9f9f9;
                display: flex;
                flex-direction: column;
                align-items: center;
                min-height: 100vh;
            }

            .header {
                width: 100%;
                background: white;
                color: #111;
                text-align: center;
                padding: 24px;
                font-size: 28px;
                font-weight: 900;
                letter-spacing: -1px;
                border-bottom: 1px solid #e0e0e0;
            }

            .box {
                margin-top: 100px;
                background: white;
                border: 2px solid #111;
                border-radius: 10px;
                padding: 40px 36px;
                width: 360px;
                text-align: center;
            }

            .box-title {
                font-size: 20px;
                font-weight: bold;
                color: #111;
                margin-bottom: 6px;
            }

            .box-sub {
                font-size: 13px;
                color: #999;
                margin-bottom: 28px;
            }

            input {
                width: 100%;
                padding: 13px;
                border: 2px solid #ddd;
                border-radius: 6px;
                font-size: 15px;
                margin-bottom: 12px;
                outline: none;
            }

            input:focus { border-color: #111; }

            button {
                background: #111;
                color: white;
                border: none;
                padding: 14px;
                border-radius: 6px;
                font-size: 16px;
                cursor: pointer;
                width: 100%;
                margin-top: 4px;
            }

            button:hover { background: #333; }

            .error {
                font-size: 13px;
                color: #dc3545;
                margin-top: 14px;
                display: none;
            }
        </style>
    </head>
    <body>

        <div class="header">okta</div>

        <div class="box">
            <div class="box-title">Sign In</div>
            <div class="box-sub">Enter your credentials to continue</div>

            <input type="email"    id="email"    placeholder="Email address">
            <input type="password" id="password" placeholder="Password">

            <button onclick="login()">Sign In</button>

            <div class="error" id="error">Incorrect email or password.</div>
        </div>

        <script>
            function login() {
                const email    = document.getElementById('email').value.trim();
                const password = document.getElementById('password').value.trim();

                if (email === 'AyaAshleyPatrick@simcorp.com' && password === '1234') {
                    window.location.href = '/victim';
                } else {
                    document.getElementById('error').style.display = 'block';
                }
            }
        </script>
    </body>
    </html>
    """
#Victim#
@app.route("/victim", methods=["GET"])
def victim_ui():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>SimCorp Verification</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }

            body {
                font-family: Arial, sans-serif;
                background: #f9f9f9;
                display: flex;
                flex-direction: column;
                align-items: center;
                min-height: 100vh;
            }

            .header {
                width: 100%;
                background: white;
                color: #111;
                text-align: center;
                padding: 24px;
                font-size: 28px;
                font-weight: 900;
                letter-spacing: -1px;
                border-bottom: 1px solid #e0e0e0;
            }

            .waiting {
                margin-top: 120px;
                color: #999;
                font-size: 16px;
                text-align: center;
            }

            .overlay {
                display: none;
                position: fixed;
                inset: 0;
                background: rgba(0,0,0,0.4);
                z-index: 10;
            }
            .overlay.show { display: block; }

            .popup {
                display: none;
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                background: white;
                border: 2px solid #111;
                border-radius: 10px;
                padding: 40px 36px;
                width: 360px;
                text-align: center;
                z-index: 20;
            }
            .popup.show { display: block; }

            .popup-title {
                font-size: 20px;
                font-weight: bold;
                color: #111;
                margin-bottom: 10px;
            }

            .popup-email {
                font-size: 16px;
                color: #333;
                margin-bottom: 8px;
            }

            .popup-question {
                font-size: 14px;
                color: #666;
                margin-bottom: 28px;
                line-height: 1.5;
            }

            .timer {
                font-size: 48px;
                font-weight: bold;
                color: #111;
                margin-bottom: 28px;
            }

            .timer.urgent { color: #333; text-decoration: underline; }

            .approve {
                background: #111;
                color: white;
                border: none;
                padding: 14px;
                border-radius: 6px;
                font-size: 16px;
                cursor: pointer;
                width: 100%;
                margin-bottom: 10px;
            }
            .approve:hover { background: #333; }

            .deny {
                background: white;
                color: #111;
                border: 2px solid #111;
                padding: 14px;
                border-radius: 6px;
                font-size: 16px;
                cursor: pointer;
                width: 100%;
            }
            .deny:hover { background: #f0f0f0; }

            .counter {
                margin-top: 40px;
                font-size: 14px;
                color: #aaa;
            }
        </style>
    </head>
    <body>

        <div class="header">okta</div>

        <div class="waiting" id="waiting">
            Monitoring for push requests...
            <div class="counter">Total requests received: <strong id="totalCount">0</strong></div>
        </div>

        <div class="overlay" id="overlay"></div>

        <div class="popup" id="popup">
            <div class="popup-title">New Sign-In Request</div>
            <div class="popup-email">AyaAshleyPatrick@simcorp.com</div>
            <div class="popup-question">Did you initiate this login attempt?<br>If not, deny it immediately.</div>

            <div class="timer" id="timer">20</div>

            <button class="approve" onclick="respond(true)">Approve</button>
            <button class="deny"    onclick="respond(false)">Deny</button>
        </div>

        <script>
            let lastCount = 0;
            let timerInterval = null;

            function startTimer() {
                let t = 20;
                const el = document.getElementById('timer');
                el.className = 'timer';
                el.innerText = t;
                clearInterval(timerInterval);
                timerInterval = setInterval(() => {
                    t--;
                    el.innerText = t;
                    if (t <= 5) el.className = 'timer urgent';
                    if (t <= 0) { clearInterval(timerInterval); respond(false); }
                }, 1000);
            }

            function showPopup() {
                document.getElementById('waiting').style.display = 'none';
                document.getElementById('popup').classList.add('show');
                document.getElementById('overlay').classList.add('show');
                startTimer();
            }

            function hidePopup() {
                document.getElementById('popup').classList.remove('show');
                document.getElementById('overlay').classList.remove('show');
                clearInterval(timerInterval);
            }

            function respond(approved) {
                hidePopup();
                fetch('/api/human-approve', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: 'AyaAshleyPatrick@simcorp.com',
                        approved: approved
                    })
                }).then(r => r.json()).then(() => {
                    document.getElementById('waiting').style.display = 'block';
                });
            }

            setInterval(() => {
                fetch('/api/push-count?user_id=AyaAshleyPatrick@simcorp.com')
                    .then(r => r.json())
                    .then(data => {
                        if (data.count > lastCount) {
                            lastCount = data.count;
                            document.getElementById('totalCount').innerText = lastCount;
                            showPopup();
                        }
                    });
            }, 1500);
        </script>
    </body>
    </html>
    """


#Push count endpoint (for the UI live counter)#
@app.route("/api/push-count", methods=["GET"])
def push_count():
    user_id = request.args.get("user_id", "unknown")
    return jsonify({"count": push_counts.get(user_id, 0)})

# Main push endpoint
@app.route("/api/push", methods=["POST"])
def handle_push():
    data = request.get_json()
    if not data or "user_id" not in data:
        return jsonify({"error": "Missing user_id"}), 400

    user_id = data["user_id"]
    push_counts[user_id] = push_counts.get(user_id, 0) + 1
    attempt_number = push_counts[user_id]

    approved = attempt_number >= APPROVAL_THRESHOLD

    log_entry = {
        "timestamp":      datetime.utcnow().isoformat() + "Z",
        "user_id":        user_id,
        "attempt_number": attempt_number,
        "approved":       approved,
        "threshold":      APPROVAL_THRESHOLD,
        "approval_type":  "timeout"
    }
    save_log_entry(log_entry)

    status_label = "✅ APPROVED" if approved else "❌ denied"
    print(f"  [push #{attempt_number:02d}] {user_id} → {status_label}")

    return jsonify({"approved": approved, "attempt_number": attempt_number})


# Human approve/deny endpoint
@app.route("/api/human-approve", methods=["POST"])
def human_approve():
    data = request.get_json()
    user_id = data.get("user_id", "unknown")
    approved = data.get("approved", False)

    log_entry = {
        "timestamp":      datetime.utcnow().isoformat() + "Z",
        "user_id":        user_id,
        "attempt_number": push_counts.get(user_id, 0),
        "approved":       approved,
        "approval_type":  "manual"
    }
    save_log_entry(log_entry)

    action = "APPROVED ✅" if approved else "DENIED ❌"
    print(f"\n  [HUMAN DECISION] {user_id} manually {action}\n")

    return jsonify({"approved": approved, "type": "manual"})

#Reset endpoint#
@app.route("/api/reset", methods=["POST"])
def reset():
    push_counts.clear()
    human_decision.clear()
    print("\n  [reset] All counters cleared.\n")
    return jsonify({"status": "reset successful"})


#Start server#
if __name__ == "__main__":
    print(f"\n[*] Mock Okta API running on http://localhost:{API_PORT}")
    print(f"[*] Victim UI available at http://localhost:{API_PORT}/victim")
    print(f"[*] Will auto-approve after {APPROVAL_THRESHOLD} push attempts")
    print(f"[*] Waiting for simulator...\n")
    app.run(port=API_PORT, debug=False)