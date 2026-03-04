import requests
import os
import json
import time

session = requests.Session()

DATA_DIR = "data"

def api_path(game):
    return game["link"].split("/room/")[0]

def room_id(game):
    return game["link"].split("/")[-1]

def tracker_id(game):
    return room_status(game)['tracker']

def game_dir(game):
    return os.path.join(DATA_DIR, room_id(game))

CACHED_API_CALLS = {}

def get_api_cached(game, route, filename, cache_timeout=None):
    global CACHED_API_CALLS
    uri = f'{api_path(game)}/api{route}'
    if uri in CACHED_API_CALLS:
        # print(f'RAMCAC {uri}')
        if cache_timeout is None or CACHED_API_CALLS[uri]['__TIMESTAMP__'] + cache_timeout > time.time():
            return CACHED_API_CALLS[uri]
    dir = game_dir(game)
    if route.startswith('/datapackage/'):
        dir = os.path.join(DATA_DIR, 'datapackage')
    if not os.path.exists(dir):
        os.mkdir(dir)
    filename = os.path.join(dir, filename)
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            data = json.loads(f.read())
            if cache_timeout is None or data['__TIMESTAMP__'] + cache_timeout > time.time():
                print(f"CACHED {uri}")
                CACHED_API_CALLS[uri] = data
                return data
    print(f"GET {uri}")
    req = session.get(uri)
    data = req.json()
    data['__TIMESTAMP__'] = time.time()
    with open(filename, 'w') as f:
        f.write(json.dumps(data, indent=4))
    CACHED_API_CALLS[uri] = data
    return data

def room_status(game):
    return get_api_cached(game, f'/room_status/{room_id(game)}', "room_status.json")

def static_tracker(game):
    return get_api_cached(game, f'/static_tracker/{tracker_id(game)}', "static_tracker.json")

def fetch_tracker(game):
    return get_api_cached(game, f'/tracker/{tracker_id(game)}', "tracker.json", cache_timeout=90)

def datapackage(game, index):
    game_name = room_status(game)["players"][index][1]
    checksum = static_tracker(game)["datapackage"][game_name]["checksum"]
    return get_api_cached(game, f"/datapackage/{checksum}", f"{checksum}.json")
