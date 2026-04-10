import requests
import os
import json
import time
import redis
import tempfile
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import hashlib
import shutil
from datetime import datetime, timezone
from collections import Counter
import subprocess

IDX_ITEM_ITEM = 0
IDX_ITEM_LOCATION = 1
IDX_ITEM_PLAYER = 2
IDX_ITEM_FLAGS = 3

session = requests.Session()
r = redis.Redis(
    # host='100.109.133.47', 
    host='127.0.0.1', 
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

def global_prop(prop):
    return PROPS_DEFAULTS.get(prop)

def log_error_to_redis(error_text):
    key = f"{REDIS_PREFIX}:errors"
    entry = json.dumps({"error": error_text, "at": datetime.now(timezone.utc).isoformat()})
    r.lpush(key, entry)
    r.ltrim(key, 0, 99)  # Keep last 100 errors

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

def slot_data_for_game(game):
    """Fetches slot data for all players in a game, cached for 24 hours. Returns [] on failure."""
    try:
        return get_api_cached(game, f'/slot_data_tracker/{tracker_id(game)}', "slot_data", cache_timeout=86400)
    except Exception as e:
        print(f"Failed to fetch slot data for {room_id(game)}: {e}")
        r.set(redis_key_for(game, "slot_data"), json.dumps([]), ex=86400)
        return []

def get_player_slot_data(game, player_index):
    """Returns the slot_data dict for a player (0-indexed), or None if unavailable."""
    all_slot_data = slot_data_for_game(game)
    for entry in all_slot_data:
        if entry.get("player") == player_index + 1:
            return entry.get("slot_data", {})
    return None

def calculate_player_logic(game, player_name, player_data, rid):
    """Calculate in-logic locations for a single player. Returns (player_name, result_list)."""
    # 1. Fetch cached Connected packet — required; fail fast if missing
    connected_key = f"{REDIS_PREFIX}:{rid}:connected:{player_name}"
    connected_raw = r.get(connected_key)
    if connected_raw is None:
        print(f"No cached Connected packet for {player_name}, skipping logic")
        return (player_name, {"in_logic": [], "calculated_at": None, "item_names": []})
    connected_packet = json.loads(connected_raw)

    # 2. Prepare data and generate hash
    game_link = game.get("link", "")
    items_received = sorted(player_data.get("items", []))
    checks_done = set(player_data.get("checks_done", []))

    # missing_locations: what the server reported minus whatever has since been checked
    missing_checks = sorted([loc for loc in connected_packet.get("missing_locations", []) if loc not in checks_done])
    player_slot_data = connected_packet.get("slot_data", {})

    hash_payload = {
        "link": game_link,
        "player": player_name,
        "items": items_received,
        "missing": missing_checks,
        "slot_data": player_slot_data,
    }
    state_hash = hashlib.sha256(json.dumps(hash_payload, sort_keys=True).encode()).hexdigest()

    # 3. Hierarchical key: REDIS_PREFIX:ROOM_ID:logic:PLAYER_NAME:HASH
    new_redis_key = f"{REDIS_PREFIX}:{rid}:logic:{player_name}:{state_hash}"

    # 4. Check if this exact state is already cached
    cached_logic = r.get(new_redis_key)
    if cached_logic:
        print(f"CACHED logic for {game['name']}/{player_name}")
        return (player_name, json.loads(cached_logic))

    # 5. Calculate logic (expensive — runs Docker)
    path = Path(os.path.join("games", game["name"]))
    if not os.path.exists(path):
        return (player_name, {"in_logic": [], "calculated_at": None, "item_names": []})

    print(f"Generating new logic for {player_name}...")
    with tempfile.TemporaryDirectory() as tmpdirname:
        dest_dir = Path(tmpdirname)
        for yaml_file in path.glob('*.yaml'):
            with open(yaml_file) as f:
                yaml_data = yaml.safe_load(f)
            if yaml_data.get("name")[:len(player_name)] == player_name:
                shutil.copy(yaml_file, dest_dir)

        data_dir = dest_dir.joinpath("data")
        os.mkdir(data_dir)

        data = datapackage(game, player_data["index"])
        id_to_name = {v: k for k, v in data["item_name_to_id"].items()}
        item_names = [id_to_name[iid[0]] for iid in player_data["items"] if iid[0] in id_to_name]

        player_game = room_status(game)["players"][player_data["index"]][1]
        checksum = static_tracker(game)["datapackage"][player_game]["checksum"]

        # Build the three packets the mock WS server will replay to UT
        room_info_packet = {
            "cmd": "RoomInfo",
            "version": {"major": 0, "minor": 6, "build": 7, "class": "Version"},
            "generator_version": {"major": 0, "minor": 6, "build": 7, "class": "Version"},
            "tags": ["AP"],
            "password": False,
            "permissions": {"release": 0, "collect": 0, "remaining": 0},
            "hint_cost": 10,
            "location_check_points": 1,
            "games": [player_game],
            "datapackage_checksums": {player_game: checksum},
            "seed_name": str(player_slot_data.get("seed_name", "0")),
            "time": time.time(),
            "class": "RoomInfo",
        }

        mod_connected = dict(connected_packet)
        mod_connected.update({
            "cmd": "Connected",
            "team": 0,
            "slot": 1,
            "players": [{"team": 0, "slot": 1, "alias": player_name, "name": player_name, "class": "NetworkPlayer"}],
            "missing_locations": missing_checks,
            "checked_locations": list(checks_done),
            "slot_info": {"1": {"name": player_name, "game": player_game, "type": 1, "group_members": [], "class": "NetworkSlot"}},
            "slot_data": player_slot_data,
        })

        received_items_packet = {
            "cmd": "ReceivedItems",
            "index": 0,
            "items": [
                {
                    "item": item[IDX_ITEM_ITEM],
                    "location": 0,
                    "player": 0,
                    "flags": 0,
                    "class": "NetworkItem"
                }
                # [item[IDX_ITEM_ITEM], item[IDX_ITEM_LOCATION], item[IDX_ITEM_PLAYER], item[IDX_ITEM_FLAGS]]
                for item in player_data.get("items", [])
                # for item in [[234782020]]
            ],
            "class": "ReceivedItems",
        }

        packets = {
            "room_info": room_info_packet,
            "connected": mod_connected,
            "received_items": received_items_packet,
            "location_names": list(data["location_name_to_id"].keys()),
            "retrieved": {
                "cmd": "Retrieved",
                "keys": {
                    # "_read_item_name_groups_Jigsaw": [],
                    # "_read_hints_0_1": [],
                    # "_read_location_name_groups_Jigsaw": []
                }
            }
        }
        with open(data_dir.joinpath("packets.json"), "w") as f:
            json.dump(packets, f)

        raw_result, docker_stdout = get_logic_items(tmpdirname, player_name)

        if raw_result is not None:
            # 6. Docker succeeded: store result, evict old hash keys
            calculated_at = datetime.now(timezone.utc).isoformat()
            result_dict = {"in_logic": raw_result, "calculated_at": calculated_at, "item_names": item_names}

            old_player_keys = list(r.scan_iter(f"{REDIS_PREFIX}:{rid}:logic:{player_name}:*"))
            if old_player_keys:
                r.delete(*old_player_keys)

            r.set(new_redis_key, json.dumps(result_dict), ex=86400)

            log_key = f"{REDIS_PREFIX}:{rid}:logic_log:{player_name}"
            r.set(log_key, json.dumps({"log": docker_stdout, "calculated_at": calculated_at}), ex=86400)

            return (player_name, result_dict)
        else:
            # 7. Docker failed: return any stale cached entry if available
            old_player_keys = list(r.scan_iter(f"{REDIS_PREFIX}:{rid}:logic:{player_name}:*"))
            if old_player_keys:
                stale_data = r.get(old_player_keys[0])
                if stale_data:
                    return (player_name, json.loads(stale_data))
            return (player_name, {"in_logic": [], "calculated_at": None, "item_names": []})


MAX_CONCURRENT_TRACKERS = 2


def calculate_trackers(game, interesting_players):
    in_logic = {}
    rid = room_id(game)

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TRACKERS) as executor:
        futures = {
            executor.submit(calculate_player_logic, game, player_name, player_data, rid): player_name
            for player_name, player_data in interesting_players.items()
        }
        for future in as_completed(futures):
            player_name, result = future.result()
            in_logic[player_name] = result

    print(f"All logic generation complete for {game['name']}")
    return in_logic

def get_logic_items(players_path, player_name, image_tag="asynctracker:latest"):
    """
    Runs the Archipelago Docker container, executes in_container.py (which
    generates the game, hosts it, injects items via !getitem, and runs Universal
    Tracker), then returns a list of location names that are currently in logic.
    """
    docker_cmd = [
        "docker", "run", "--rm",
        "-v", f"{os.path.abspath(players_path)}:/opt/Archipelago/Players",
        "-v", f"{os.path.abspath('custom_worlds')}:/opt/Archipelago/custom_worlds",
        image_tag,
        "python3", "/opt/Archipelago/in_container.py", "--name", player_name
    ]

    try:
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            check=True
        )

        stdout = result.stdout
        # print(result.stdout)
        # print('---')
        # print(result.stderr)
        items = []

        if "In logic list:" in stdout:
            parts = stdout.split("In logic list:")
            raw_list = parts[1].strip().splitlines()
            items = [line.strip() for line in raw_list if line.strip()]
        else:
            error_output = f"Docker container exited without 'In logic list:' in stdout:\n{stdout}"
            if result.stderr:
                error_output += f"\nstderr:\n{result.stderr}"
            print(error_output)
            return (None, error_output)

        return (items, stdout)

    except subprocess.CalledProcessError as e:
        error_output = f"Docker error:\n{e.stderr}"
        print(error_output)
        return (None, error_output)