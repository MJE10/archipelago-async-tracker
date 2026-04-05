import requests
import os
import json
import time
import redis
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from logic_tracker.run_logic import get_logic_items
from pathlib import Path
import hashlib
import shutil
from datetime import datetime, timezone
from collections import Counter

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

def set_redis_prefix(prefix):
    global REDIS_PREFIX
    REDIS_PREFIX = prefix

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
        # print(f"CACHED {uri}")
        return json.loads(str(redis_value))

    print(f"GET {uri}")
    req = session.get(uri)
    data = req.json()
    r.set(redis_key, json.dumps(data), ex=cache_timeout)
    return data

def room_status(game):
    return get_api_cached(game, f'/room_status/{room_id(game)}', "room_status", cache_timeout=600)

def static_tracker(game):
    return get_api_cached(game, f'/static_tracker/{tracker_id(game)}', "static_tracker")

def fetch_tracker(game):
    key = redis_key_for(game, "tracker")
    is_cached = r.get(key) is not None
    data = get_api_cached(game, f'/tracker/{tracker_id(game)}', "tracker", cache_timeout=game_prop(game, "tracker_refresh"))
    if not is_cached:
        r.set(redis_key_for(game, "tracker_fetched_at"), datetime.now(timezone.utc).isoformat())
    return data

def get_tracker_fetched_at(game):
    return r.get(redis_key_for(game, "tracker_fetched_at"))

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
    all_keys = list(r.scan_iter(f"{REDIS_PREFIX}:{rid}:*"))
    if all_keys:
        r.delete(*all_keys)
        print(f"Wiped {len(all_keys)} keys for game {rid}")

def calculate_player_logic(game, player_name, player_data, rid):
    """Calculate in-logic locations for a single player. Returns (player_name, result_list)."""
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

    # 2. Hierarchical key: REDIS_PREFIX:ROOM_ID:logic:PLAYER_NAME:HASH
    new_redis_key = f"{REDIS_PREFIX}:{rid}:logic:{player_name}:{state_hash}"

    # 3. Check if this exact state is already cached
    cached_logic = r.get(new_redis_key)
    if cached_logic:
        print(f"CACHED logic for {game['name']}/{player_name}")
        return (player_name, json.loads(cached_logic))

    # 4. Calculate logic (expensive — runs Docker)
    path = Path(os.path.join("games", game["name"]))
    if not os.path.exists(path):
        return (player_name, {"in_logic": [], "calculated_at": None, "item_names": []})

    print(f"Generating new logic for {player_name}...")
    with tempfile.TemporaryDirectory() as tmpdirname:
        dest_dir = Path(tmpdirname)
        for yaml_file in path.glob('*.yaml'):
            shutil.copy(yaml_file, dest_dir)

        data_dir = dest_dir.joinpath("data")
        os.mkdir(data_dir)

        data = datapackage(game, player_data["index"])
        id_to_name = {v: k for k, v in data["item_name_to_id"].items()}
        item_names = [id_to_name[iid[0]] for iid in player_data["items"] if iid[0] in id_to_name]

        location_names = list(data["location_name_to_id"].keys())

        with open(data_dir.joinpath("item_names.json"), "w") as f:
            json.dump(item_names, f)

        with open(data_dir.joinpath("location_names.json"), "w") as f:
            json.dump(location_names, f)

        checks_done = set(player_data.get("checks_done", []))
        name_to_id = data["location_name_to_id"]

        raw_result, docker_stdout = get_logic_items(tmpdirname, player_name)

        if raw_result is not None:
            # 5. Docker succeeded: build result, delete old keys, store new entry
            result = [loc for loc in raw_result if name_to_id.get(loc) not in checks_done]
            calculated_at = datetime.now(timezone.utc).isoformat()
            result_dict = {"in_logic": result, "calculated_at": calculated_at, "item_names": item_names}

            old_player_keys = list(r.scan_iter(f"{REDIS_PREFIX}:{rid}:logic:{player_name}:*"))
            if old_player_keys:
                r.delete(*old_player_keys)

            r.set(new_redis_key, json.dumps(result_dict), ex=86400)

            log_key = f"{REDIS_PREFIX}:{rid}:logic_log:{player_name}"
            r.set(log_key, json.dumps({"log": docker_stdout, "calculated_at": calculated_at}), ex=86400)

            return (player_name, result_dict)
        else:
            # 6. Docker failed: return any stale cached entry if available
            old_player_keys = list(r.scan_iter(f"{REDIS_PREFIX}:{rid}:logic:{player_name}:*"))
            if old_player_keys:
                stale_data = r.get(old_player_keys[0])
                if stale_data:
                    return (player_name, json.loads(stale_data))
            return (player_name, {"in_logic": [], "calculated_at": None, "item_names": []})


def calculate_trackers(game, interesting_players):
    in_logic = {}
    rid = room_id(game)

    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(calculate_player_logic, game, player_name, player_data, rid): player_name
            for player_name, player_data in interesting_players.items()
        }
        for future in as_completed(futures):
            player_name, result = future.result()
            in_logic[player_name] = result

    print(f"All logic generation complete for {game['name']}")
    return in_logic
