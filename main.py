import yaml
import argparse
from util import *
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, send_from_directory, request
from flask_socketio import SocketIO
from extra.notifications import get_active_subscriptions, update_subscriptions, check_and_notify

app = Flask(__name__, static_folder='static')
app.json.sort_keys = False
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

GAMES_YAML = "games.yaml"

ALL_GAME_RESULTS = {}
REFRESH_TRACKERS = []
REFRESH_ALL = False
SUPER_REFRESH = []
REFRESH_NOW = threading.Event()
PENDING_LISTENER_REFRESH = set()
PENDING_LISTENER_REFRESH_LOCK = threading.Lock()

@app.route('/')
def index():
    """Serves the index.html from the static directory."""
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    """Serves all other static files (css, js, etc.)."""
    return send_from_directory(app.static_folder, path)

@app.route('/games')
def get_games():
    global ALL_GAME_RESULTS
    """Returns the current state of ALL_GAME_RESULTS as JSON."""
    return jsonify(ALL_GAME_RESULTS)

@socketio.on('connect')
def handle_ws_connect():
    from flask_socketio import emit
    emit('game_update', ALL_GAME_RESULTS)

@app.route('/logic_log')
def get_logic_log():
    game_name = request.args.get('game')
    player_name = request.args.get('player')
    if not game_name or not player_name:
        return jsonify({"error": "game and player params required"}), 400
    with open(GAMES_YAML, 'r') as f:
        games = yaml.load(f, Loader=yaml.SafeLoader)
    game = games.get(game_name)
    if not game or "link" not in game:
        return jsonify({"error": "game not found"}), 404
    game["name"] = game_name
    raw = r.get(redis_key_for(game, f"logic_log:{player_name}"))
    if not raw:
        return jsonify({"log": None, "calculated_at": None})
    return jsonify(json.loads(raw))

@app.route('/refresh_tracker/<path:game_name>')
def trigger_refresh_tracker(game_name):
    """Adds a game to the queue to have its tracker JSON refreshed."""
    global REFRESH_TRACKERS
    if game_name not in REFRESH_TRACKERS:
        REFRESH_TRACKERS.append(game_name)
    
    update_all_games()
    
    return jsonify({
        "status": "queued",
        "action": "refresh_tracker",
        "game": game_name,
        "current_queue_size": len(REFRESH_TRACKERS)
    })

@app.route('/refresh_all')
def trigger_refresh_all():
    global REFRESH_ALL
    REFRESH_ALL = True
    
    update_all_games()
    for key in r.scan_iter(f"{REDIS_PREFIX}:*:logic:*"):
        r.delete(key)

    return "Ok"

@app.route('/notifications', methods=['GET'])
def get_notifications():
    return jsonify(get_active_subscriptions())

@app.route('/notifications', methods=['POST'])
def post_notifications():
    data = request.json or {}
    new_subs = data.get("subscriptions", {})
    current_logic = {}
    for game_name, game_data in ALL_GAME_RESULTS.items():
        current_logic[game_name] = {}
        for player_name, pdata in game_data.get("players", {}).items():
            current_logic[game_name][player_name] = pdata.get("in_logic", [])
    update_subscriptions(new_subs, current_logic)
    return jsonify({"status": "ok"})

@app.route('/super_refresh/<path:game_name>')
def trigger_super_refresh(game_name):
    """Adds a game to the queue to have ALL cached data wiped."""
    global SUPER_REFRESH
    if game_name not in SUPER_REFRESH:
        SUPER_REFRESH.append(game_name)
    
    update_all_games()
    
    return jsonify({
        "status": "queued",
        "action": "super_refresh",
        "game": game_name,
        "current_queue_size": len(SUPER_REFRESH)
    })

def background_update_loop():
    """Runs the infinite loop in a separate thread."""
    while True:
        # try:
        update_all_games()
        # except Exception as e:
        #     print(f"Error in update loop: {e}")
        REFRESH_NOW.wait(timeout=30)
        REFRESH_NOW.clear()

def update_all_games():
    global ALL_GAME_RESULTS, REFRESH_TRACKERS, SUPER_REFRESH, REFRESH_ALL
    with PENDING_LISTENER_REFRESH_LOCK:
        for name in PENDING_LISTENER_REFRESH:
            if name not in REFRESH_TRACKERS:
                REFRESH_TRACKERS.append(name)
        PENDING_LISTENER_REFRESH.clear()
    with open(GAMES_YAML, 'r') as f:
        games = yaml.load(f, Loader=yaml.SafeLoader)

    memory = {}
    all_results = {}
    index = 0
    games_to_process = []

    # First pass: setup result structure, clear caches, collect games to process
    for (name, game) in games.items():
        if name == "default":
            register_prop_defaults(game)
            continue
        if game is None:
            game = {}
        game["name"] = name
        if "link" in game and (game["name"] in REFRESH_TRACKERS or REFRESH_ALL):
            clear_tracker_cache(game)
        if "link" in game and game["name"] in SUPER_REFRESH:
            clear_game_cache(game)
        all_results[name] = {
            "index": index,
            "settings": game,
            "players": {}
        }
        index += 1
        if "links" not in all_results[name]["settings"]:
            all_results[name]["settings"]["links"] = {}
        if "link" in game:
            all_results[name]['settings']["links"].update({
                "Room": game["link"],
                "Tracker": f"{api_path(game)}/tracker/{tracker_id(game)}"
            })
            if name not in memory:
                memory[name] = {
                    "hints": {},
                    "players": {}
                }
                for player in room_status(game)["players"]:
                    memory[name][player[0]] = {
                        "items": {},
                        "locations": 0
                    }
            games_to_process.append((name, game, memory[name]))

    # Second pass: process all games in parallel
    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(process_game, name, game, mem): name
            for (name, game, mem) in games_to_process
        }
        for future in as_completed(futures):
            name = futures[future]
            per_player, game_checks_done, game_checks_total = future.result()
            all_results[name]["players"] = per_player
            all_results[name]["game_checks_done"] = game_checks_done
            all_results[name]["game_checks_total"] = game_checks_total
            socketio.emit('game_update', {name: all_results[name]})

    for (name, game, _) in games_to_process:
        all_results[name]["tracker_fetched_at"] = get_tracker_fetched_at(game)

    ALL_GAME_RESULTS = all_results
    REFRESH_TRACKERS = []
    SUPER_REFRESH = []
    REFRESH_ALL = False
    check_and_notify(ALL_GAME_RESULTS)

def process_game(name, game, memory):
    print(f"Now processing: {name}")

    # API calls
    room = room_status(game)
    for idx in range(len(room_status(game)['players'])):
        datapackage(game, idx)
        break

    tracker = fetch_tracker(game)
    static = static_tracker(game)

    # Determine what has changed
    per_player = {}
    for player in room_status(game)["players"]:
        if player[0] in game_prop(game, "players") or len(game_prop(game, "players")) == 0:
            per_player[player[0]] = {
                "ut_link": f"ut://{api_path(game).split("://")[1]}:{room["last_port"]}/{player[0]}/{str(game_prop(game, "password"))}",
                "in_logic": [],
                "num_locations_checked": 0,
                "num_locations_total": 1
            }
    game_checks_total = 0
    for p, player in enumerate(static["player_locations_total"]):
        game_checks_total += player["total_locations"]
        player_name = player_idx_to_name(game, p)
        if player_name in per_player:
            per_player[player_name]["num_locations_total"] = player["total_locations"]

    new_hints = {}
    updated_hints = {}
    for p in tracker["hints"]:
        for hint in p["hints"]:
            id = hint_id(hint)
            if id not in memory["hints"] and id not in new_hints:
                new_hints[id] = hint
            if id in memory["hints"] and memory["hints"][id] != hint: 
                updated_hints[id] = hint
    new_items = {}
    non_new_items = {}
    new_locations = {}
    interesting_players = {}
    for (p, player) in enumerate(tracker["activity_timers"]):
        player_name = player_idx_to_name(game, p)
        if player_name in per_player:
            per_player[player_name]["last_activity"] = player["time"]
    for (p, player) in enumerate(tracker["player_items_received"]):
        player_name = player_idx_to_name(game, p)
        data = datapackage(game, p)
        if player_name in game_prop(game, "players") or len(game_prop(game, "players")) == 0:
            interesting_players[player_name] = {"index": p, "items": player["items"], "checks_done": []}
        gui_items = {}
        for item in player["items"]:
            item = item[IDX_ITEM_ITEM]
            curr_non_new = non_new_items.get(item, 0)
            item_name = None
            for item_name2 in data["item_name_to_id"]:
                if data["item_name_to_id"][item_name2] == item:
                    item_name = item_name2
                    break
            if item_name is not None:
                gui_items[item_name] = gui_items.get(item_name, 0) + 1
            if curr_non_new < memory[player_name]["items"].get(item, 0):
                non_new_items[item] = curr_non_new + 1
            else:
                if player_name not in new_items:
                    new_items[player_name] = {}
                new_items[player_name][item] = new_items[player_name].get(item, 0) + 1
        if player_name in per_player:
            per_player[player_name]["items"] = gui_items
    game_checks_done = 0
    for (p, player) in enumerate(tracker["player_checks_done"]):
        game_checks_done += len(player["locations"])
        player_name = player_idx_to_name(game, p)
        if player_name in per_player:
            per_player[player_name]["num_locations_checked"] = len(player["locations"])
            interesting_players[player_name]["checks_done"] = player["locations"]
        locations_done = len(player["locations"])
        new_locations[player_name] = locations_done - memory[player_name]["locations"]
    
    # Merge extra/starting items (e.g. start inventory) into each player's item list
    extra_items_key = redis_key_for(game, "extra_items")
    extra_items_hash = r.hgetall(extra_items_key)
    if extra_items_hash:
        for player_name, pdata in interesting_players.items():
            existing_loc_player = {
                (item[IDX_ITEM_LOCATION], item[IDX_ITEM_PLAYER])
                for item in pdata["items"]
            }
            for field, val_str in extra_items_hash.items():
                entry = json.loads(val_str)
                if entry["player"] != player_name:
                    continue
                ni = entry["item"]
                if (ni["location"], ni["player"]) in existing_loc_player:
                    r.hdel(extra_items_key, field)
                else:
                    pdata["items"].append([ni["item"], ni["location"], ni["player"], ni["flags"]])
                    if player_name in per_player:
                        data = datapackage(game, pdata["index"])
                        item_name = next((k for k, v in data["item_name_to_id"].items() if v == ni["item"]), None)
                        if item_name:
                            gui = per_player[player_name].setdefault("items", {})
                            gui[item_name] = gui.get(item_name, 0) + 1

    # Mark source locations from extra_items as checked for the sending player.
    # The tracker data may not yet reflect these checks, but extra_items tells
    # us they happened, so the logic calculator should treat them as done.
    if extra_items_hash:
        for val_str in extra_items_hash.values():
            ni = json.loads(val_str)["item"]
            if ni["location"] < 0 or ni["player"] <= 0:
                continue  # skip special locations / server-generated items
            sender_name = player_idx_to_name(game, ni["player"] - 1)
            if sender_name in interesting_players:
                if ni["location"] not in interesting_players[sender_name]["checks_done"]:
                    interesting_players[sender_name]["checks_done"].append(ni["location"])

    # Determine things that are in logic
    in_logic = calculate_trackers(game, interesting_players)
    for player_name in in_logic:
        if player_name in per_player:
            result_dict = in_logic[player_name]
            per_player[player_name]["in_logic"] = result_dict.get("in_logic", [])
            per_player[player_name]["logic_calculated_at"] = result_dict.get("calculated_at")
            logic_counts = dict(Counter(result_dict.get("item_names", [])))
            gui_counts = per_player[player_name].get("items", {})
            per_player[player_name]["logic_items_match"] = (logic_counts == gui_counts)

    return (per_player, game_checks_done, game_checks_total)
    # return {
    #     # "new_hints": new_hints,
    #     # "updated_hints": updated_hints,
    #     # "new_items": new_items,
    #     # "new_locations": new_locations,
    #     # "in_logic": in_logic,
    #     # "per_player": per_player
    # }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config", nargs="?", default="games.yaml", help="Path to games yaml config file")
    args = parser.parse_args()

    GAMES_YAML = args.config

    with open(GAMES_YAML, 'r') as f:
        config = yaml.load(f, Loader=yaml.SafeLoader)
    defaults = config.get("default", {}) or {}
    port = defaults.get("port", 5151)
    redis_prefix = defaults.get("redis_prefix", "ap2")
    set_redis_prefix(redis_prefix)

    from extra.listener import run_listener
    for game_name, game in config.items():
        if game_name == "default" or not game or "link" not in game:
            continue
        game = dict(game)
        game["name"] = game_name
        if game_prop(game, "global_listener"):
            t = threading.Thread(
                target=run_listener,
                args=(game, game_name, PENDING_LISTENER_REFRESH, PENDING_LISTENER_REFRESH_LOCK, REFRESH_NOW),
                daemon=True
            )
            t.start()
            print(f"Started listener thread for {game_name}")

    update_thread = threading.Thread(target=background_update_loop, daemon=True)
    update_thread.start()

    socketio.run(app, host='0.0.0.0', port=port)