import yaml
from util import *
import threading
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder='static')

ALL_GAME_RESULTS = {}
REFRESH_TRACKERS = []
SUPER_REFRESH = []

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
        time.sleep(30)

def update_all_games():
    global ALL_GAME_RESULTS, REFRESH_TRACKERS, SUPER_REFRESH
    with open("games.yaml", 'r') as f:
        games = yaml.load(f, Loader=yaml.SafeLoader)
        # print(json.dumps(games, indent=4))

    memory = {}
    # if os.path.exists("memory.json"):
    #     with open("memory.json", "r") as f:
    #         memory = json.loads(f.read())
    #     memory_keys = memory.keys()
    #     for k in memory_keys:
    #         if k not in games:
    #             memory.pop(k)
    
    # any_updated = False
    all_results = {}
    for (name, game) in games.items():
        if name == "default":
            register_prop_defaults(game)
            continue
        game["name"] = name
        if game["name"] in REFRESH_TRACKERS:
            clear_tracker_cache(game)
        if game["name"] in SUPER_REFRESH:
            clear_game_cache(game)
        # if the tracker has not changed, then we don't need to continue
        # if tracker_info_unchanged(game):
        #     continue
        # any_updated = True
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
        all_results[name] = process_game(name, game, memory[name])
    ALL_GAME_RESULTS = all_results
    REFRESH_TRACKERS = []
    SUPER_REFRESH = []
    
    # if any_updated:
    #     with open("memory.json", "w") as f:
    #         f.write(json.dumps(memory))

def process_game(name, game, memory):
    print(f"Now processing: {name}")

    # API calls
    room_status(game)
    for idx in range(len(room_status(game)['players'])):
        datapackage(game, idx)
        break

    tracker = fetch_tracker(game)
    static = static_tracker(game)

    # Determine what has changed
    per_player = {}
    for player in room_status(game)["players"]:
        if player[0] in game_prop(game, "players"):
            per_player[player[0]] = {
                "in_logic": [],
                "num_locations_checked": 0,
                "num_locations_total": 1
            }
    for p, player in enumerate(static["player_locations_total"]):
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
        if player_name in game_prop(game, "players"):
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
    for (p, player) in enumerate(tracker["player_checks_done"]):
        player_name = player_idx_to_name(game, p)
        if player_name in per_player:
            per_player[player_name]["num_locations_checked"] = len(player["locations"])
            interesting_players[player_name]["checks_done"] = player["locations"]
        locations_done = len(player["locations"])
        new_locations[player_name] = locations_done - memory[player_name]["locations"]
    
    # Determine things that are in logic
    in_logic = calculate_trackers(game, interesting_players)
    for player_name in in_logic:
        if player_name in per_player:
            per_player[player_name]["in_logic"] = in_logic[player_name]
    # print(in_logic)

    return per_player
    # return {
    #     # "new_hints": new_hints,
    #     # "updated_hints": updated_hints,
    #     # "new_items": new_items,
    #     # "new_locations": new_locations,
    #     # "in_logic": in_logic,
    #     # "per_player": per_player
    # }


if __name__ == "__main__":
    # 2. Start the background thread
    update_thread = threading.Thread(target=background_update_loop, daemon=True)
    update_thread.start()

    # 3. Start the Flask server
    # host='0.0.0.0' makes it accessible on your local network
    app.run(host='0.0.0.0', port=5151)