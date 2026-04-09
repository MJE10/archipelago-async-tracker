import json
import time
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from websocket import create_connection
from util import api_path, room_status, player_name_to_idx, redis_key_for, game_prop, r


def run_listener(game, game_name, pending_set, pending_lock, refresh_event):
    """Persistent WebSocket listener for a game. Runs in a daemon thread.
    On ItemSend PrintJSON events, writes to the extra_items Redis hash and
    wakes the background update loop for immediate processing."""
    while True:
        try:
            room = room_status(game)
            port = room["last_port"]
            host = api_path(game).split("://")[1]
            protocol = "wss" if api_path(game).startswith("https") else "ws"
            ws_url = f"{protocol}://{host}:{port}"
            password = str(game_prop(game, "password") or "")

            player_name = game_prop(game, "global_listener")
            player_index = player_name_to_idx(game, player_name)
            player_game_name = room["players"][player_index][1]

            ws = create_connection(ws_url, timeout=30)
            ws.send(json.dumps([{
                "cmd": "Connect",
                "password": password,
                "game": player_game_name,
                "name": player_name,
                "items_handling": 0,
                "version": {"major": 0, "minor": 6, "build": 6, "class": "Version"},
                "tags": ["TextOnly"],
                "slot_data": False,
                "uuid": "async-tracker-listener",
            }]))

            print(f"[listener:{game_name}] Connected as '{player_name}'")

            while True:
                for msg in json.loads(ws.recv()):
                    if msg.get("cmd") == "PrintJSON" and msg.get("type") == "ItemSend":
                        _handle_item_send(game, game_name, msg, pending_set, pending_lock, refresh_event)

        except Exception as e:
            print(f"[listener:{game_name}] Disconnected: {e}, reconnecting in 10s...")
            time.sleep(10)


def _handle_item_send(game, game_name, msg, pending_set, pending_lock, refresh_event):
    receiving_slot = msg["receiving"]   # 1-indexed player slot
    item = msg["item"]                  # NetworkItem dict

    players = room_status(game)["players"]
    receiving_player_name = players[receiving_slot - 1][0]

    field = f"{item['player']}_{item['location']}"
    value = json.dumps({"player": receiving_player_name, "item": item})
    was_new = r.hsetnx(redis_key_for(game, "extra_items"), field, value)
    if was_new:
        print(f"[listener:{game_name}] ItemSend -> {receiving_player_name}: item {item['item']}")
    else:
        print(f"[listener:{game_name}] Duplicate item {field}, receiver already has it")

    # Always trigger a refresh: even if the receiver's item was a duplicate,
    # the sending player just checked a location and needs their logic updated.
    with pending_lock:
        pending_set.add(game_name)
    refresh_event.set()
