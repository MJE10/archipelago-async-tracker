import requests
import json
import time
import os

# Configuration
ROOM_URL = "https://archipelago.gg/room/ccMRWalsRYyzj14FXBTDHg"
API_URL = "https://archipelago.gg/api/tracker/q4apJ8WiT5y_o75NGoKe8A"
SAVE_PATH = "/mnt/m/primary/documents/gaming/ap/gang/tracker.json"
INTERVAL = 1.5 * 60 * 60  # 1.5 hours in seconds

def update_tracker():
    try:
        # 1. Ping the Room URL (ignore response)
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Pinging room...")
        requests.get(ROOM_URL, timeout=10)

        # 2. Get the API data
        print("Fetching tracker JSON...")
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()  # Check for HTTP errors
        
        data = response.json()

        # 3. Ensure directory exists
        os.makedirs(os.path.dirname(SAVE_PATH), exist_ok=True)

        # 4. Save to file
        with open(SAVE_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        
        print(f"Success! Data saved to {SAVE_PATH}")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    print(f"Script started. Running every {INTERVAL/3600} hours.")
    while True:
        update_tracker()
        print(f"Waiting {INTERVAL/3600} hours for next update...")
        time.sleep(INTERVAL)