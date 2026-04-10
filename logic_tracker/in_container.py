import os
import glob
import json
import argparse
import subprocess
import time
import threading
import asyncio
import shutil

import websockets


async def handle_client(websocket, room_info, connected, received_items, retrieved):
    """Serve the three pre-built packets to a connecting UT client."""
    # Step 1: server sends RoomInfo immediately on connection
    await websocket.send(json.dumps([room_info]))

    # Step 2: wait for client packets (GetDataPackage and/or Connect)
    async for raw in websocket:
        try:
            pkts = json.loads(raw)
        except Exception:
            continue
        if not isinstance(pkts, list):
            pkts = [pkts]
        for pkt in pkts:
            cmd = pkt.get("cmd")
            if cmd == "GetDataPackage":
                print("GetDataPackage packet")
                # UT will fall back to its local .apworld cache; send empty response
                await websocket.send(json.dumps([{"cmd": "DataPackage", "data": {"games": {}}}]))
            elif cmd == "Connect":
                print("Connect packet")
                # Step 3: respond with Connected then ReceivedItems
                await websocket.send(json.dumps([connected]))
                await websocket.send(json.dumps([received_items]))
                await websocket.send(json.dumps([{"cmd": "Retrieved", "keys": {"_read_race_mode": 0}}]))
                await websocket.send(json.dumps([retrieved]))
                # Keep connection alive until UT closes it
                try:
                    async for _ in websocket:
                        pass
                except websockets.exceptions.ConnectionClosed:
                    pass
                return


async def run_server(port, room_info, connected, received_items, retrieved):
    async def handler(websocket):
        await handle_client(websocket, room_info, connected, received_items, retrieved)

    async with websockets.serve(handler, "localhost", port):
        await asyncio.Future()  # run until daemon thread is killed


def main():
    print(time.time())

    parser = argparse.ArgumentParser(description="Archipelago Logic Runner")
    parser.add_argument("--name", default="player", help="Player slot name")
    parser.add_argument("--port", type=int, default=38243, help="Port for mock WS server")
    args = parser.parse_args()

    base_path = "/opt/Archipelago"
    players_path = os.path.join(base_path, "Players")
    custom_worlds_path = os.path.join(base_path, "custom_worlds")
    worlds_path = os.path.join(base_path, "worlds")

    packets_file = os.path.join(players_path, "data", "packets.json")
    with open(packets_file) as f:
        packets = json.load(f)

    room_info = packets["room_info"]
    connected = packets["connected"]
    received_items = packets["received_items"]
    location_names = packets["location_names"]
    retrieved = packets["retrieved"]

    # Build a set of stripped names for fast membership testing
    stripped_location_names = {l.split('(')[0].strip() for l in location_names}

    print(f"Loaded {len(location_names)} location names, {len(connected.get('missing_locations', []))} missing, "
          f"{len(received_items.get('items', []))} items received")

    # Copy tracker.apworld (and any game worlds) into worlds/ so UT can find them
    os.makedirs(worlds_path, exist_ok=True)
    for apworld in glob.glob(os.path.join(custom_worlds_path, "*.apworld")):
        dest = os.path.join(worlds_path, os.path.basename(apworld))
        shutil.copy2(apworld, dest)
        print(f"Copied {os.path.basename(apworld)} to worlds/")

    # Start mock WebSocket server in a daemon thread
    def run_loop():
        asyncio.run(run_server(args.port, room_info, connected, received_items, retrieved))

    server_thread = threading.Thread(target=run_loop, daemon=True)
    server_thread.start()
    time.sleep(1)  # give server a moment to bind

    launcher_path = os.path.join(base_path, "ArchipelagoLauncher")

    print(f"--- Running Universal Tracker for {args.name} on port {args.port} ---")

    tracker_result = subprocess.run(
        [
            "xvfb-run", "-a", "-s", "-screen 0 1024x768x24",
            launcher_path, "Universal Tracker", "--",
            "--name", args.name,
            "--list",
            "--nogui",
            f"archipelago://localhost:{args.port}"
        ],
        capture_output=True,
        text=True
    )

    print('--- tracker stdout ---')
    print(tracker_result.stdout)
    print('--- tracker stderr ---')
    print(tracker_result.stderr)

    # Keep lines whose pre-paren text matches a known location name;
    # emit the full name including parentheses (helpful context for the player)
    in_logic = [
        line.strip() for line in tracker_result.stdout.splitlines()
        if line.split('(')[0].strip() in stripped_location_names
    ]

    print("In logic list:")
    for loc in in_logic:
        print(loc)


if __name__ == "__main__":
    main()
