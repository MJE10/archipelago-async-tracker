import requests
import os
import json
import time
import redis
import tempfile
from logic_tracker.run_logic import get_logic_items
from pathlib import Path
import hashlib
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
    in_logic = {}
    for player_name in interesting_players:
        player_data = interesting_players[player_name]
        
        # 1. Prepare data for hashing
        game_link = game.get("link", "")
        items_received = sorted(player_data.get("items", []))
        
        # Calculate missing checks (needed for the hash)
        datapack = datapackage(game, player_data["index"])["location_name_to_id"]
        missing_checks = sorted([
            datapack[k] for k in datapack.keys() 
            if k not in player_data.get("checks_done", [])
        ])

        # 2. Create a unique hash for this specific state
        # Sorting lists ensures the hash is consistent regardless of item order
        hash_payload = {
            "link": game_link,
            "player": player_name,
            "items": items_received,
            "missing": missing_checks
        }
        state_hash = hashlib.sha256(json.dumps(hash_payload, sort_keys=True).encode()).hexdigest()
        redis_key = f"tracker:{state_hash}"

        # 3. Check Redis cache
        cached_logic = r.get(redis_key)
        if cached_logic:
            print(f"CACHE HIT for {player_name} (key: {redis_key})")
            in_logic[player_name] = json.loads(cached_logic)
            continue

        # 4. Cache Miss: Run the expensive logic calculation
        path = Path(os.path.join("games", game["name"]))
        if not os.path.exists(path):
            in_logic[player_name] = []
            continue

        print(f"CACHE MISS: Generating logic for {game['name']}/{player_name}")
        with tempfile.TemporaryDirectory() as tmpdirname:
            dest_dir = Path(tmpdirname)
            for yaml_file in path.glob('*.yaml'):
                shutil.copy(yaml_file, dest_dir)
            
            data_dir = dest_dir.joinpath("data")
            os.mkdir(data_dir)
            
            # Save items
            with open(data_dir.joinpath("items_received.json"), "w") as f:
                f.write(json.dumps(player_data["items"]))
            
            # Save missing checks
            with open(data_dir.joinpath("missing_checks.json"), "w") as f:
                f.write(json.dumps(missing_checks))

            # Run logic engine
            result = get_logic_items(tmpdirname, player_name)
            in_logic[player_name] = result

            # 5. Store result in Redis for 24 hours (86,400 seconds)
            r.set(redis_key, json.dumps(result), ex=86400)

    return in_logic
