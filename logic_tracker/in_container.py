import subprocess
import os
import glob
import time
import json
import argparse
import sys
from websocket import create_connection
from datetime import datetime

def main():
    now = datetime.now()
    print(now.strftime("%Y/%m/%d %H:%M:%S"))

    # Setup Argument Parsing
    parser = argparse.ArgumentParser(description="Archipelago Automation Script")
    parser.add_argument("--name", default="MJE10_celeste", help="Player name for connection")
    parser.add_argument("--port", type=int, default=38281, help="Port for the host and tracker")
    args = parser.parse_args()

    base_path = "/opt/Archipelago"
    work_dir = os.path.join(base_path, "Players/script/")
    launcher_path = os.path.join(base_path, "ArchipelagoLauncher")

    # Ensure the directory exists and change to it
    os.makedirs(work_dir, exist_ok=True)
    os.chdir(work_dir)

    # 1. Run Generate synchronously
    # print("--- Running Generation ---")
    # gen_result = subprocess.run(
    #     [launcher_path, "Generate"],
    #     capture_output=True,
    #     text=True
    # )
    # print(gen_result.stdout)
    # print(gen_result.stderr)
    # # You can access gen_result.stdout or gen_result.stderr here if needed
    # print("Generation complete.")

    # # 2. Find the zip file and run Host asynchronously
    # output_dir = os.path.join(base_path, "output")
    # zip_files = glob.glob(os.path.join(output_dir, "*.zip"))

    # if not zip_files:
    #     print(f"Error: No zip file found in {output_dir}")
    #     sys.exit(1)
    
    # target_zip = zip_files[0]
    # print(f"--- Hosting: {os.path.basename(target_zip)} on port {args.port} ---")

    # # Start Host asynchronously (output goes to current process stdout/stderr)
    # host_proc = subprocess.Popen([
    #     launcher_path, "Host", "--", "--port", str(args.port), target_zip
    # ])

    # 3. WebSocket communication
    time.sleep(5) # Wait for server to initialize
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

        # Listen for 3 seconds
        start_time = time.time()
        ws.settimeout(0.5) # Short timeout to allow loop to check time
        while time.time() - start_time < 2:
            try:
                result = ws.recv()
                print(f"Received Packet: {result}")
            except Exception:
                # Likely a timeout, just continue until 3s is up
                continue
        
        # Send !getitem commands
        ws.send(json.dumps([{"cmd": "Say", "text": "!getitem Strawberry"}]))

        # Listen for 3 seconds
        start_time = time.time()
        ws.settimeout(0.5) # Short timeout to allow loop to check time
        while time.time() - start_time < 2:
            try:
                result = ws.recv()
                print(f"Received Packet: {result}")
            except Exception:
                # Likely a timeout, just continue until 3s is up
                continue

        ws.close()
    except Exception as e:
        print(f"WebSocket Error: {e}")

    # 4. Run Universal Tracker synchronously
    print(f"--- Running Universal Tracker for {args.name} ---")
    tracker_cmd = [
        launcher_path, "Universal Tracker", "--",
        "--name", args.name,
        "--list",
        "--nogui",
        f"archipelago://localhost:{args.port}"
    ]
    
    tracker_result = subprocess.run(
        tracker_cmd,
        capture_output=True,
        text=True
    )
    
    # Printing results of the tracker run
    print("Tracker Output:")
    print(tracker_result.stdout)
    if tracker_result.stderr:
        print("Tracker Errors:", tracker_result.stderr)

    print("--- Script Task Sequence Completed ---")
    # Note: host_proc is still running in the background. 
    # Use host_proc.terminate() if you want to kill it at the end of the script.

if __name__ == "__main__":
    main()