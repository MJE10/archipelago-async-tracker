"""
Fetches real slot data for a specific player by connecting to the Archipelago
WebSocket server and reading the Connected packet. Updates the Redis cache
indefinitely (no TTL) so it takes precedence over the API-based cache.

Usage:
    python fetch_slot_data.py <game_name> [player_name] [--config games.yaml]
"""

import argparse
import json
import yaml
import sys
from websocket import create_connection

import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from util import (
    api_path, room_id, room_status, player_name_to_idx, redis_key_for,
    set_redis_prefix, register_prop_defaults, game_prop,
)
import redis as redis_lib


def fetch_for_player(game, player_name, player_index, port, host, protocol, password, r):
    player_game_name = room_status(game)["players"][player_index][1]
    ws_url = f"{protocol}://{host}:{port}"

    print(f"Connecting to {ws_url} as '{player_name}' (slot {player_index + 1}, game: {player_game_name})...")

    ws = create_connection(ws_url)
    connect_msg = [{
        "cmd": "Connect",
        "password": password,
        "game": player_game_name,
        "uuid": "slot-data-fetcher",
        "name": player_name,
        "items_handling": 0,
        "version": {"major": 0, "minor": 6, "build": 6, "class": "Version"},
        "tags": ["TextOnly"],
        "slot_data": True,
    }]
    ws.send(json.dumps(connect_msg))

    connected_packet = None
    for _ in range(10):
        raw = ws.recv()
        messages = json.loads(raw)
        for msg in messages:
            if msg.get("cmd") == "Connected":
                connected_packet = msg
                break
        if connected_packet is not None:
            break

    ws.close()

    if connected_packet is None:
        print(f"Error: never received a Connected packet for '{player_name}'", file=sys.stderr)
        return False

    slot_data = connected_packet.get("slot_data", {})
    print(f"slot_data for '{player_name}': {json.dumps(slot_data, indent=2)}")

    # Store the full Connected packet
    connected_key = redis_key_for(game, f"connected:{player_name}")
    r.set(connected_key, json.dumps(connected_packet))
    print(f"Cached Connected packet for '{player_name}' in Redis key '{connected_key}' with no expiry.")

    # Update or insert the slot_data entry for this player
    redis_key = redis_key_for(game, "slot_data")
    raw_cached = r.get(redis_key)
    current = json.loads(raw_cached) if raw_cached else []

    slot_number = player_index + 1
    updated = False
    for entry in current:
        if entry.get("player") == slot_number:
            entry["slot_data"] = slot_data
            updated = True
            break
    if not updated:
        current.append({"player": slot_number, "slot_data": slot_data})

    r.set(redis_key, json.dumps(current))
    print(f"Cached slot data for player {slot_number} ('{player_name}') in Redis key '{redis_key}' with no expiry.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Fetch slot data via WebSocket and cache it in Redis.")
    parser.add_argument("game_name", help="Name of the game as defined in games.yaml")
    parser.add_argument("player_name", nargs="?", default=None, help="Player name to fetch slot data for (omit for all players)")
    parser.add_argument("--config", default="games.yaml", help="Path to games.yaml")
    args = parser.parse_args()

    with open(args.config, "r") as f:
        games = yaml.load(f, Loader=yaml.SafeLoader)

    defaults = games.get("default", {}) or {}
    redis_prefix = defaults.get("redis_prefix", "ap")
    set_redis_prefix(redis_prefix)
    register_prop_defaults(defaults)

    game = games.get(args.game_name)
    if game is None:
        print(f"Error: game '{args.game_name}' not found in {args.config}", file=sys.stderr)
        sys.exit(1)
    if "link" not in game:
        print(f"Error: game '{args.game_name}' has no link", file=sys.stderr)
        sys.exit(1)
    game["name"] = args.game_name

    from util import r

    room = room_status(game)
    players = room["players"]
    port = room["last_port"]
    host = api_path(game).split("://")[1]
    protocol = "wss" if api_path(game).startswith("https") else "ws"
    password = str(game_prop(game, "password") or "")

    if args.player_name is not None:
        player_index = player_name_to_idx(game, args.player_name)
        if players[player_index][0] != args.player_name:
            print(f"Error: player '{args.player_name}' not found in room", file=sys.stderr)
            sys.exit(1)
        success = fetch_for_player(game, args.player_name, player_index, port, host, protocol, password, r)
        if not success:
            sys.exit(1)
    else:
        failures = []
        for player_index, player_info in enumerate(players):
            player_name = player_info[0]
            success = fetch_for_player(game, player_name, player_index, port, host, protocol, password, r)
            if not success:
                failures.append(player_name)
        if failures:
            print(f"Failed to fetch Connected packet for: {failures}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
