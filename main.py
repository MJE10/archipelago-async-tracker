import yaml
from util import *
import tempfile
from logic_tracker.run_logic import get_logic_items
from pathlib import Path
import shutil
import threading
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder='static')

ALL_GAME_RESULTS = {}

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

def background_update_loop():
    """Runs the infinite loop in a separate thread."""
    while True:
        try:
            update_all_games()
        except Exception as e:
            print(f"Error in update loop: {e}")
        time.sleep(30)

def update_all_games():
    global ALL_GAME_RESULTS
    with open("games.yaml", 'r') as f:
        games = yaml.load(f, Loader=yaml.SafeLoader)
        print(json.dumps(games, indent=4))

    memory = {}
    if os.path.exists("memory.json"):
        with open("memory.json", "r") as f:
            memory = json.loads(f.read())
        memory_keys = memory.keys()
        for k in memory_keys:
            if k not in games:
                memory.pop(k)
    
    # any_updated = False
    all_results = {}
    for (name, game) in games.items():
        if name == "default":
            register_prop_defaults(game)
            continue
        game["name"] = name
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

    # Determine what has changed
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
    for (p, player) in enumerate(tracker["player_items_received"]):
        player_name = player_idx_to_name(game, p)
        if player_name in game_prop(game, "players"):
            interesting_players[player_name] = {"index": p, "items": player["items"], "checks_done": []}
        for item in player["items"]:
            item = item[IDX_ITEM_ITEM]
            curr_non_new = non_new_items.get(item, 0)
            if curr_non_new < memory[player_name]["items"].get(item, 0):
                non_new_items[item] = curr_non_new + 1
            else:
                if player_name not in new_items:
                    new_items[player_name] = {}
                new_items[player_name][item] = new_items[player_name].get(item, 0) + 1
    for (p, player) in enumerate(tracker["player_checks_done"]):
        player_name = player_idx_to_name(game, p)
        if player_name in interesting_players:
            interesting_players[player_name]["checks_done"] = player["locations"]
        locations_done = len(player["locations"])
        new_locations[player_name] = locations_done - memory[player_name]["locations"]
    
    # Determine things that are in logic
    in_logic = {}
    for player_name in interesting_players:
        in_logic[player_name] = []
        # Do we have YAMLs?
        path = Path(os.path.join("games", game["name"]))
        if not os.path.exists(path):
            continue
        print(f"Generating logic for {game["name"]}/{player_name}")
        # Set up temporary directory for YAMLs
        with tempfile.TemporaryDirectory() as tmpdirname:
            # Copy all .yaml files from games/name folder into the temporary directory
            dest_dir = Path(tmpdirname)
            for yaml_file in path.glob('*.yaml'):
                shutil.copy(yaml_file, dest_dir)
            # Output all items received
            data_dir = dest_dir.joinpath("data")
            os.mkdir(data_dir)
            with open(data_dir.joinpath("items_received.json"), "w") as f:
                f.write(json.dumps(interesting_players[player_name]["items"]))
            # Output all checks done
            with open(data_dir.joinpath("missing_checks.json"), "w") as f:
                datapack = datapackage(game, interesting_players[player_name]["index"])["location_name_to_id"]
                incomplete_checks = [datapack[k] for k in datapack.keys() if k not in interesting_players[player_name]["checks_done"]]
                f.write(json.dumps(incomplete_checks))
            in_logic[player_name] = get_logic_items(tmpdirname, player_name)
    print(in_logic)

    return {
        # "new_hints": new_hints,
        # "updated_hints": updated_hints,
        # "new_items": new_items,
        # "new_locations": new_locations,
        "in_logic": in_logic
    }


if __name__ == "__main__":
    # 2. Start the background thread
    update_thread = threading.Thread(target=background_update_loop, daemon=True)
    update_thread.start()

    # 3. Start the Flask server
    # host='0.0.0.0' makes it accessible on your local network
    app.run(host='0.0.0.0', port=5000)