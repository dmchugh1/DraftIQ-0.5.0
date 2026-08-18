import math
import os

from flask import Flask, jsonify, render_template, request
import numpy as np
import pandas as pd

from engine import DraftIQEngine

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8MB upload cap

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Single shared engine instance - this is a personal single-user draft tool,
# mirroring the original notebook's single global draft_state.
engine = DraftIQEngine()

# Auto-load the bundled sample dataset if present, so the app has something
# to show immediately. Real usage: upload your own players.csv from the UI.
_sample_path = os.path.join(UPLOAD_DIR, "sample_players.csv")
if os.path.exists(_sample_path):
    engine.load_players(_sample_path)


def clean(obj):
    """Recursively convert numpy/pandas scalar types to native Python and
    replace NaN/inf with None, so jsonify doesn't choke on either."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        return None if (math.isnan(val) or math.isinf(val)) else val
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if obj is pd.NA or (isinstance(obj, float) and pd.isna(obj)):
        return None
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    return obj


def df_records(df):
    if df is None or len(df) == 0:
        return []
    return clean(df.replace({pd.NA: None}).to_dict("records"))


# ----------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ----------------------------------------------------------------------
# Setup / league config
# ----------------------------------------------------------------------

@app.route("/api/upload", methods=["POST"])
def upload_players():
    file = request.files.get("file")
    if not file or file.filename == "":
        return jsonify({"ok": False, "message": "No file provided"}), 400

    save_path = os.path.join(UPLOAD_DIR, "players.csv")
    file.save(save_path)

    try:
        engine.load_players(save_path)
    except Exception as e:
        return jsonify({"ok": False, "message": f"Failed to parse CSV: {e}"}), 400

    return jsonify({"ok": True, "players_loaded": len(engine.players_df)})


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        data = request.get_json(force=True)
        engine.num_teams = int(data.get("num_teams", engine.num_teams))
        engine.my_team = int(data.get("my_team", engine.my_team))
        engine.rounds = int(data.get("rounds", engine.rounds))
        if engine.loaded:
            engine.league = engine._create_league()
            engine.draft_order = engine._snake_order()
            engine.reset_draft()

    return jsonify({
        "num_teams": engine.num_teams,
        "my_team": engine.my_team,
        "roster_size": engine.roster_size,
        "rounds": engine.rounds,
        "scoring": engine.scoring,
        "starters": engine.starters,
        "loaded": engine.loaded,
        "players_loaded": len(engine.players_df) if engine.loaded else 0,
    })


# ----------------------------------------------------------------------
# Draft state
# ----------------------------------------------------------------------

def _require_loaded():
    if not engine.loaded:
        return jsonify({"ok": False, "message": "No player data loaded yet. Upload a players.csv first."}), 400
    return None


@app.route("/api/state")
def state():
    err = _require_loaded()
    if err:
        return err
    return jsonify({
        "pick": engine.draft_state["pick"],
        "round": engine.draft_state["round"],
        "current_team": engine.get_current_team_number(),
        "my_team": engine.my_team,
        "on_the_clock": engine.get_current_team_number() == engine.my_team,
        "players_remaining": len(engine.get_available_players()),
        "history": engine.draft_state["history"][-15:],
    })


@app.route("/api/roster")
def roster():
    err = _require_loaded()
    if err:
        return err
    return jsonify({
        "roster": engine.get_team_roster(engine.my_team),
        "needs": engine.get_roster_needs(),
        "position_counts": engine.get_position_counts(),
    })


@app.route("/api/league")
def league():
    err = _require_loaded()
    if err:
        return err
    return jsonify({"league": engine.league})


@app.route("/api/available")
def available():
    err = _require_loaded()
    if err:
        return err
    count = int(request.args.get("count", 25))
    df = engine.get_available_players().sort_values("rank").head(count)
    return jsonify({"players": df_records(df)})


@app.route("/api/reset", methods=["POST"])
def reset():
    err = _require_loaded()
    if err:
        return err
    engine.reset_draft()
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# Draft actions
# ----------------------------------------------------------------------

@app.route("/api/pick", methods=["POST"])
def pick():
    err = _require_loaded()
    if err:
        return err
    data = request.get_json(force=True)
    player_name = data.get("player")
    if not player_name:
        return jsonify({"ok": False, "message": "player is required"}), 400
    result = engine.draftiq_pick(player_name)
    return jsonify(clean(result))


@app.route("/api/simulate_to_me", methods=["POST"])
def simulate_to_me():
    err = _require_loaded()
    if err:
        return err
    picks = engine.simulate_opponents_until_user()
    return jsonify({"ok": True, "picks": picks, "state": {
        "pick": engine.draft_state["pick"],
        "round": engine.draft_state["round"],
        "current_team": engine.get_current_team_number(),
    }})


@app.route("/api/draft_any", methods=["POST"])
def draft_any():
    """Assign a pick to whichever team is currently on the clock (for
    manually running a live draft where opponents pick for themselves)."""
    err = _require_loaded()
    if err:
        return err
    data = request.get_json(force=True)
    player_name = data.get("player")
    result = engine.draft_player(player_name)
    return jsonify(clean(result))


# ----------------------------------------------------------------------
# Intelligence endpoints
# ----------------------------------------------------------------------

@app.route("/api/recommendations")
def recommendations():
    err = _require_loaded()
    if err:
        return err
    count = int(request.args.get("count", 10))
    df = engine.get_draft_recommendations(count)
    return jsonify({"recommendations": df_records(df)})


@app.route("/api/decision")
def decision():
    err = _require_loaded()
    if err:
        return err
    count = int(request.args.get("count", 10))
    df = engine.draftiq_decision_engine(count)
    return jsonify({"decisions": df_records(df)})


@app.route("/api/on_clock")
def on_clock():
    err = _require_loaded()
    if err:
        return err
    result = engine.draftiq_on_clock_decision()
    return jsonify(clean(result))


@app.route("/api/alerts")
def alerts():
    err = _require_loaded()
    if err:
        return err
    return jsonify({
        "draft_alerts": engine.get_draft_alerts(),
        "position_runs": engine.get_position_run_alerts(),
    })


@app.route("/api/compare", methods=["POST"])
def compare():
    err = _require_loaded()
    if err:
        return err
    data = request.get_json(force=True)
    names = data.get("players", [])
    df = engine.compare_players(names)
    return jsonify({"comparison": df_records(df)})


@app.route("/api/opportunity_cost", methods=["POST"])
def opportunity_cost():
    err = _require_loaded()
    if err:
        return err
    data = request.get_json(force=True)
    names = data.get("players", [])
    df = engine.opportunity_cost(names)
    return jsonify({"opportunity_cost": df_records(df)})


@app.route("/api/what_if", methods=["POST"])
def what_if():
    err = _require_loaded()
    if err:
        return err
    data = request.get_json(force=True)
    player = data.get("player")
    result = engine.what_if_i_wait(player)
    return jsonify(clean(result))


@app.route("/api/strategy_report", methods=["POST"])
def strategy_report():
    err = _require_loaded()
    if err:
        return err
    data = request.get_json(force=True) or {}
    names = data.get("players")
    result = engine.draft_strategy_report(names)
    return jsonify(clean(result))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
