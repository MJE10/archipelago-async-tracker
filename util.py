import requests
import os
import json
import time
import redis
import tempfile
from logic_tracker.run_logic import get_logic_items
from pathlib import Path
import shutil

IDX_ITEM_ITEM = 0
IDX_ITEM_LOCATION = 1
IDX_ITEM_PLAYER = 2
IDX_ITEM_FLAGS = 3

session = requests.Session()
r = redis.Redis(
    host='100.109.133.47', 
    port=6379, 
    # password='your_strong_password',
    decode_responses=True
)

REDIS_PREFIX = "ap"

PROPS_DEFAULTS = {}

def register_prop_defaults(props):
    global PROPS_DEFAULTS
    PROPS_DEFAULTS = props

def game_prop(game, prop):
    if prop in game:
        return game[prop]
    elif prop in PROPS_DEFAULTS:
        return PROPS_DEFAULTS[prop]
    else:
        return None

def api_path(game):
    return game["link"].split("/room/")[0]

def room_id(game):
    return game["link"].split("/")[-1]

def tracker_id(game):
    return room_status(game)['tracker']

def hint_id(hint):
    return f'{hint[1]}_{hint[2]}'

def player_name_to_idx(game, name):
    i = 0
    players = room_status(game)["players"]
    while i < len(players):
        if players[i][0] == name:
            return i
        i += 1
    return 0

def player_idx_to_name(game, idx):
    return room_status(game)["players"][idx][0]

def redis_key_for(game, kind, per_game=True):
    kind = kind.strip('/').replace('/', ':')
    if per_game:
        return f'{REDIS_PREFIX}:{room_id(game)}:{kind}'
    else:
        return f'{REDIS_PREFIX}:{kind}'

def get_api_cached(game, route, key, per_game=True, cache_timeout=None):
    uri = f'{api_path(game)}/api{route}'
    redis_key = redis_key_for(game, key, per_game=per_game)

    redis_value = r.get(redis_key)
    if redis_value is not None:
        print(f"CACHED {uri}")
        return json.loads(str(redis_value))

    print(f"GET {uri}")
    req = session.get(uri)
    data = req.json()
    r.set(redis_key, json.dumps(data), ex=cache_timeout)
    return data

def room_status(game):
    return get_api_cached(game, f'/room_status/{room_id(game)}', "room_status")

def static_tracker(game):
    return get_api_cached(game, f'/static_tracker/{tracker_id(game)}', "static_tracker")

def fetch_tracker(game):
    return get_api_cached(game, f'/tracker/{tracker_id(game)}', "tracker", cache_timeout=game_prop(game, "tracker_refresh"))

def tracker_info_unchanged(game):
    return r.get(redis_key_for(game, "tracker")) is not None

def datapackage(game, index):
    game_name = room_status(game)["players"][index][1]
    checksum = static_tracker(game)["datapackage"][game_name]["checksum"]
    return get_api_cached(game, f"/datapackage/{checksum}", f"datapackage:{checksum}", per_game=False)

def calculate_trackers(game, interesting_players):
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
    return in_logic
