"""
FlashArray ZTP Simulator
Mocks the FlashArray ZTP REST API on port 8081 for testing without real hardware.
"""
import os
import threading
import time
from flask import Flask, jsonify, request

app = Flask(__name__)

PHASE_DELAY = int(os.environ.get("PHASE_DELAY", "5"))

PHASES = [
    "install-not-started",
    "install-in-progress",
    "download-in-progress",
    "ct0-install-in-progress",
    "ct1-install-in-progress",
    "install-complete",
]

state = {
    "status": "install-not-started",
    "errors": [],
}
state_lock = threading.Lock()
_sim_thread = None


def _advance_phases():
    """Background thread: step through install phases with a delay between each."""
    for phase in PHASES[1:]:
        time.sleep(PHASE_DELAY)
        with state_lock:
            if state["status"] == "install-not-started":
                # reset was called — stop advancing
                return
            state["status"] = phase
        print(f"[simulator] phase → {phase}", flush=True)


# ── ZTP PureSoftwareInstall ───────────────────────────────────────────────────

@app.route("/array-purity-installations", methods=["GET"])
def get_install_status():
    with state_lock:
        return jsonify({"status": state["status"], "errors": list(state["errors"])})


@app.route("/array-purity-installations", methods=["PATCH"])
def start_install():
    global _sim_thread
    body = request.get_json(force=True, silent=True) or {}

    if not body.get("package_path") or not body.get("sig_file_path"):
        return jsonify({"error": "package_path and sig_file_path are required"}), 400

    with state_lock:
        state["status"] = "install-in-progress"
        state["errors"] = []

    # Start phase-advancement thread (restart if already running)
    _sim_thread = threading.Thread(target=_advance_phases, daemon=True)
    _sim_thread.start()

    print(f"[simulator] install started: {body.get('package_path')}", flush=True)
    return jsonify({"message": "Install initiated", "status": "install-in-progress"}), 200


# ── ZTP PureInitialize ────────────────────────────────────────────────────────

@app.route("/array-initial-config", methods=["PATCH"])
def initialize():
    body = request.get_json(force=True, silent=True) or {}

    if not body.get("array_name"):
        return jsonify({"error": "array_name is required"}), 400

    print(f"[simulator] initialize accepted for array: {body.get('array_name')}", flush=True)
    return jsonify({
        "message": "Array initial configuration accepted",
        "array_name": body.get("array_name"),
    }), 200


# ── Test helpers ──────────────────────────────────────────────────────────────

@app.route("/reset", methods=["POST"])
def reset():
    with state_lock:
        state["status"] = "install-not-started"
        state["errors"] = []
    print("[simulator] state reset to install-not-started", flush=True)
    return jsonify({"message": "Reset to install-not-started"}), 200


@app.route("/", methods=["GET"])
def index():
    with state_lock:
        current = state["status"]
    return jsonify({
        "service": "FlashArray ZTP Simulator",
        "current_status": current,
        "phase_delay_seconds": PHASE_DELAY,
        "endpoints": {
            "GET  /array-purity-installations": "Check install status",
            "PATCH /array-purity-installations": "Start install simulation",
            "PATCH /array-initial-config": "Accept initialize config",
            "POST /reset": "Reset install state",
        },
    })


if __name__ == "__main__":
    print(f"[simulator] Starting on port 8081 (PHASE_DELAY={PHASE_DELAY}s)", flush=True)
    app.run(host="0.0.0.0", port=8081, debug=False)
