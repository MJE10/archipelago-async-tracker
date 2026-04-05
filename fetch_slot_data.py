"""
Fetches real slot data for a specific player by connecting to the Archipelago
WebSocket server and reading the Connected packet. Updates the Redis cache
indefinitely (no TTL) so it takes precedence over the API-based cache.

Usage:
    python fetch_slot_data.py <game_name> <player_name> [--config games.yaml]
"""

import argparse
import json
import yaml
import sys
from websocket import create_connection
from util import (
    api_path, room_id, room_status, player_name_to_idx, redis_key_for,
    set_redis_prefix, register_prop_defaults, game_prop,
)
import redis as redis_lib


def main():
    parser = argparse.ArgumentParser(description="Fetch slot data via WebSocket and cache it in Redis.")
    parser.add_argument("game_name", help="Name of the game as defined in games.yaml")
    parser.add_argument("player_name", help="Player name to fetch slot data for")
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

    room = room_status(game)
    player_index = player_name_to_idx(game, args.player_name)
    players = room["players"]
    if players[player_index][0] != args.player_name:
        print(f"Error: player '{args.player_name}' not found in room", file=sys.stderr)
        sys.exit(1)

    player_game_name = players[player_index][1]
    port = room["last_port"]
    host = api_path(game).split("://")[1]
    protocol = "wss" if api_path(game).startswith("https") else "ws"
    ws_url = f"{protocol}://{host}:{port}"

    password = str(game_prop(game, "password") or "")

    print(f"Connecting to {ws_url} as '{args.player_name}' (slot {player_index + 1}, game: {player_game_name})...")

    ws = create_connection(ws_url)
    connect_msg = [{
        "cmd": "Connect",
        "password": password,
        "game": player_game_name,
        "uuid": "slot-data-fetcher",
        "name": args.player_name,
        "items_handling": 0,
        "version": {"major": 0, "minor": 6, "build": 6, "class": "Version"},
        "tags": ["TextOnly"],
        "slot_data": True,
    }]
    ws.send(json.dumps(connect_msg))

    slot_data = None
    for _ in range(10):
        raw = ws.recv()
        messages = json.loads(raw)
        for msg in messages:
            if msg.get("cmd") == "Connected":
                slot_data = msg.get("slot_data", {})
                break
        if slot_data is not None:
            break

    ws.close()

    if slot_data is None:
        print("Error: never received a Connected packet", file=sys.stderr)
        sys.exit(1)

    print(f"slot_data: {json.dumps(slot_data, indent=2)}")

    # Read current cached array (may be from the API or a previous run)
    from util import r
    redis_key = redis_key_for(game, "slot_data")
    raw_cached = r.get(redis_key)
    current = json.loads(raw_cached) if raw_cached else []

    # Update or insert the entry for this player
    slot_number = player_index + 1
    updated = False
    for entry in current:
        if entry.get("player") == slot_number:
            entry["slot_data"] = slot_data
            updated = True
            break
    if not updated:
        current.append({"player": slot_number, "slot_data": slot_data})

    # Cache indefinitely (no TTL) — this is a manual override
    r.set(redis_key, json.dumps(current))
    print(f"Cached slot data for player {slot_number} ('{args.player_name}') in Redis key '{redis_key}' with no expiry.")


if __name__ == "__main__":
    main()
