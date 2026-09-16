import os
from flask import Flask, jsonify, request

from config import API_PORT, APPROVAL_THRESHOLD
from identity_controller import (
    AuthenticationError,
    IdentityController,
    load_token_principals,
)
from shared.actions import ActionContractError
from shared.events import EventLedger

app = Flask(__name__)
event_ledger = EventLedger(
    os.getenv("NETSTRIKE_EVENT_LEDGER", "output/identity_events.jsonl")
)
controller = IdentityController(
    exercise_id=os.getenv("NETSTRIKE_EXERCISE_ID", "silent-spider"),
    run_id=os.getenv("NETSTRIKE_RUN_ID", "local-development"),
    tokens=load_token_principals(),
    event_sink=event_ledger.append,
    approval_threshold=APPROVAL_THRESHOLD,
)


# Login#
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


# Victim#
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


# Push count endpoint (for the UI live counter)#
@app.route("/api/push-count", methods=["GET"])
def push_count():
    user_id = request.args.get("user_id", "unknown")
    if user_id not in {"sarah", "AyaAshleyPatrick@simcorp.com"}:
        return jsonify({"error": "Unknown synthetic identity"}), 404
    return jsonify({"count": controller.state.mfa["sarah"]["push_count"]})


@app.route("/api/action", methods=["POST"])
def submit_action():
    """Authenticate and submit one server-correlated safe action."""

    try:
        principal = controller.authenticate(request.headers.get("Authorization"))
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        result = controller.submit(principal, payload)
    except AuthenticationError as exc:
        return jsonify({"error": str(exc)}), 401
    except (ValueError, TypeError, ActionContractError) as exc:
        return jsonify({"error": str(exc)}), 400

    if result["status"] == "denied":
        status = 409 if result["error_code"] == "idempotency_conflict" else 403
        return jsonify(result), status
    return jsonify(result), 200


# Removed state-changing compatibility routes. Delivery clients must use the
# authenticated /api/action boundary so actor identity cannot be forged.
@app.route("/api/push", methods=["POST"])
def handle_push():
    return jsonify({"error": "Use authenticated /api/action"}), 410


# Human approve/deny endpoint
@app.route("/api/human-approve", methods=["POST"])
def human_approve():
    return jsonify({"error": "Use authenticated /api/action"}), 410


# Reset endpoint#
@app.route("/api/reset", methods=["POST"])
def reset():
    return (
        jsonify({"error": "Reset is disabled pending the approved reset workflow"}),
        410,
    )


# Start server#
if __name__ == "__main__":
    print(f"\n[*] Mock Okta API running on http://localhost:{API_PORT}")
    print(f"[*] Victim UI available at http://localhost:{API_PORT}/victim")
    print(f"[*] Will auto-approve after {APPROVAL_THRESHOLD} push attempts")
    print(f"[*] Waiting for simulator...\n")
    app.run(port=API_PORT, debug=False)
