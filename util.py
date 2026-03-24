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

def clear_tracker_cache(game):
    """Deletes the cached tracker JSON to force a refresh of items/checks."""
    key = redis_key_for(game, "tracker")
    r.delete(key)
    print(f"Cleared tracker cache for room: {room_id(game)}")

def clear_game_cache(game):
    """Deletes all cached information associated with a specific room ID."""
    rid = room_id(game)
    # Clear general API cache (prefixed with ap:room_id)
    api_keys = list(r.scan_iter(f"{REDIS_PREFIX}:{rid}:*"))
    # Clear logic tracker cache (prefixed with tracker:room_id)
    logic_keys = list(r.scan_iter(f"tracker:{rid}:*"))
    
    all_keys = api_keys + logic_keys
    if all_keys:
        r.delete(*all_keys)
        print(f"Wiped {len(all_keys)} keys for game {rid}")

def calculate_trackers(game, interesting_players):
    in_logic = {}
    rid = room_id(game)

    for player_name in interesting_players:
        player_data = interesting_players[player_name]
        
        # 1. Prepare data and generate hash
        game_link = game.get("link", "")
        items_received = sorted(player_data.get("items", []))
        
        datapack = datapackage(game, player_data["index"])["location_name_to_id"]
        missing_checks = sorted([
            datapack[k] for k in datapack.keys() 
            if datapack[k] not in player_data.get("checks_done", [])
        ])

        hash_payload = {
            "link": game_link,
            "player": player_name,
            "items": items_received,
            "missing": missing_checks
        }
        state_hash = hashlib.sha256(json.dumps(hash_payload, sort_keys=True).encode()).hexdigest()
        
        # 2. Hierarchical key for targeted deletion
        # Format: tracker:ROOM_ID:PLAYER_NAME:HASH
        new_redis_key = f"tracker:{rid}:{player_name}:{state_hash}"

        # 3. Check if this exact state is already cached
        cached_logic = r.get(new_redis_key)
        if cached_logic:
            print(f"CACHED logic for {game["name"]}/{player_name}")
            in_logic[player_name] = json.loads(cached_logic)
            continue

        # 4. Cache Miss: First, remove any OLD logic hashes for THIS player
        # Since logic only moves forward, we don't need the old calculations
        old_player_keys = list(r.scan_iter(f"tracker:{rid}:{player_name}:*"))
        if old_player_keys:
            r.delete(*old_player_keys)

        # 5. Calculate logic (Expensive operation)
        path = Path(os.path.join("games", game["name"]))
        if not os.path.exists(path):
            in_logic[player_name] = []
            continue

        print(f"Generating new logic for {player_name}...")
        with tempfile.TemporaryDirectory() as tmpdirname:
            dest_dir = Path(tmpdirname)
            for yaml_file in path.glob('*.yaml'):
                shutil.copy(yaml_file, dest_dir)
            
            data_dir = dest_dir.joinpath("data")
            os.mkdir(data_dir)
            
            with open(data_dir.joinpath("items_received.json"), "w") as f:
                f.write(json.dumps(player_data["items"]))
            
            with open(data_dir.joinpath("missing_checks.json"), "w") as f:
                f.write(json.dumps(missing_checks))
            
            # with open(data_dir.joinpath("datapackage.json"), "w") as f:
            #     f.write(json.dumps(datapackage(game, player_data["index"])))
            # with open("datapackage.json", "w") as f:
            #     f.write(json.dumps(datapackage(game, player_data["index"])))

            result = get_logic_items(tmpdirname, player_name)
            # print(result)
            in_logic[player_name] = result

            # 6. Store in Redis for 24 hours
            r.set(new_redis_key, json.dumps(result), ex=86400)

    print(f"All logic generation complete for {game['name']}")
    return in_logic
