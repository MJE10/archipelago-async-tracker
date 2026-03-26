import subprocess
import os
import glob
import time
import json
import argparse
import sys
import shutil
from websocket import create_connection
from datetime import datetime


def main():
    now = datetime.now()
    print(now.strftime("%Y/%m/%d %H:%M:%S"))

    print("KIVY_NO_CONSOLELOG:", os.getenv('KIVY_NO_CONSOLELOG'), file=sys.stderr)

    parser = argparse.ArgumentParser(description="Archipelago Logic Runner")
    parser.add_argument("--name", default="MJE10_celeste", help="Player slot name")
    parser.add_argument("--port", type=int, default=38243, help="Port for the AP server")
    args = parser.parse_args()

    base_path = "/opt/Archipelago"
    players_path = os.path.join(base_path, "Players")
    custom_worlds_path = os.path.join(base_path, "custom_worlds")
    worlds_path = os.path.join(base_path, "worlds")
    output_dir = os.path.join(base_path, "output")
    launcher_path = os.path.join(base_path, "ArchipelagoLauncher")

    items_file = os.path.join(players_path, "data", "item_names.json")
    locations_file = os.path.join(players_path, "data", "location_names.json")

    with open(items_file, "r") as f:
        item_names = json.load(f)
        print(f"items: {item_names[:10]}...")

    with open(locations_file, "r") as f:
        location_names = json.load(f)
        print(f"locations: {location_names[:10]}...")
        location_names = set(location_names)

    # 1. Copy custom worlds (tracker.apworld + any game worlds) into worlds/ so
    #    Generate can discover them
    os.makedirs(worlds_path, exist_ok=True)
    for apworld in glob.glob(os.path.join(custom_worlds_path, "*.apworld")):
        dest = os.path.join(worlds_path, os.path.basename(apworld))
        shutil.copy2(apworld, dest)
        print(f"Copied {os.path.basename(apworld)} to worlds/")

    # 2. Generate a game from the player YAMLs in Players/
    # Clear any stale zips first so we always host the freshly generated seed
    os.makedirs(output_dir, exist_ok=True)
    for old_zip in glob.glob(os.path.join(output_dir, "*.zip")):
        os.remove(old_zip)
    print("--- Running Generation ---")
    gen_result = subprocess.run(
        [launcher_path, "Generate"],
        capture_output=True,
        text=True,
        cwd=base_path
    )
    print(gen_result.stdout)
    if gen_result.stderr:
        print(gen_result.stderr, file=sys.stderr)

    # 3. Find the generated zip and start the server in the background
    zip_files = glob.glob(os.path.join(output_dir, "*.zip"))
    if not zip_files:
        print(f"Error: No zip file found in {output_dir}", file=sys.stderr)
        sys.exit(1)
    target_zip = zip_files[0]
    print(f"--- Hosting: {os.path.basename(target_zip)} on port {args.port} ---")

    host_proc = subprocess.Popen([
        launcher_path, "Host", "--", "--port", str(args.port), target_zip
    ])

    # 4. Wait for server to come up, then connect via WebSocket
    time.sleep(10)
    ws_url = f"ws://localhost:{args.port}"

    try:
        print(f"--- Connecting to WebSocket: {ws_url} ---")
        ws = create_connection(ws_url)

        connect_msg = [{
            "cmd": "Connect",
            "password": "",
            "game": "",
            "uuid": "1234",
            "name": args.name,
            "items_handling": 0,
            "version": {"major": 0, "minor": 6, "build": 6, "class": "Version"},
            "tags": ["TextOnly"],
            "slot_data": False,
        }]
        ws.send(json.dumps(connect_msg))

        # Drain connection response
        start_time = time.time()
        ws.settimeout(0.5)
        while time.time() - start_time < 1:
            try:
                ws.recv()
            except Exception:
                continue

        # 5. Give the player all the items they currently have via !getitem
        for item_name in item_names:
            ws.send(json.dumps([{"cmd": "Say", "text": f"!getitem {item_name}"}]))

        # Wait for item grants to be processed server-side
        time.sleep(1)
        ws.close()

    except Exception as e:
        print(f"WebSocket Error: {e}", file=sys.stderr)
        host_proc.terminate()
        sys.exit(1)

    # 6. Run Universal Tracker in --list mode to get in-logic locations
    print(f"--- Running Universal Tracker for {args.name} ---")
    tracker_result = subprocess.run(
        [
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
    print('---  ---')

    # 7. Filter UT's stdout: any line whose content exactly matches a known
    #    location name is in logic
    location_names = [l.split('(')[0].strip() for l in location_names]
    in_logic = [
        line.split('(')[0].strip() for line in tracker_result.stdout.splitlines()
        if line.split('(')[0].strip() in location_names
    ]

    print("In logic list:")
    for loc in in_logic:
        print(loc)

    # if tracker_result.stderr:
    #     print("Tracker Errors:", tracker_result.stderr, file=sys.stderr)

    host_proc.terminate()
    # print("--- Done ---")


if __name__ == "__main__":
    main()
