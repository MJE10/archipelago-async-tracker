import yaml
from util import *

def main():
    with open("games.yaml", 'r') as f:
        games = yaml.load(f, Loader=yaml.SafeLoader)
        print(json.dumps(games, indent=4))

    memory = {}
    if os.path.exists("memory.json"):
        with open("memory.json", "r") as f:
            memory = json.loads(f.read())
        memory_keys = memory.keys()
        for k in memory_keys:
            if k not in games:
                memory.pop(k)
    
    any_updated = False
    for (name, game) in games.items():
        if name == "all":
            continue
        game["name"] = name
        # if the tracker has not changed, then we don't need to continue
        if tracker_info_unchanged(game):
            continue
        any_updated = True
        if name not in memory:
            memory[name] = {
                "hints": {},
                "players": {}
            }
            for player in room_status(game)["players"]:
                memory[name][player[0]] = {
                    "items": {},
                    "locations": 0
                }
        process_game(name, game, memory[name])
    
    if any_updated:
        with open("memory.json", "w") as f:
            f.write(json.dumps(memory))

def process_game(name, game, memory):
    print(f"Now processing: {name}")

    # API calls
    room_status(game)
    for idx in range(len(room_status(game)['players'])):
        datapackage(game, idx)
        break

    tracker = fetch_tracker(game)

    # Determine what has changed
    new_hints = {}
    updated_hints = {}
    for p in tracker["hints"]:
        for hint in p["hints"]:
            id = hint_id(hint)
            if id not in memory["hints"] and id not in new_hints:
                new_hints[id] = hint
            if id in memory["hints"] and memory["hints"][id] != hint: 
                updated_hints[id] = hint
    new_items = {}
    non_new_items = {}
    new_locations = {}
    for (p, player) in enumerate(tracker["player_items_received"]):
        player_name = player_idx_to_name(game, p)
        for item in player["items"]:
            item = item[IDX_ITEM_ITEM]
            curr_non_new = non_new_items.get(item, 0)
            if curr_non_new < memory[player_name]["items"].get(item, 0):
                non_new_items[item] = curr_non_new + 1
            else:
                if player_name not in new_items:
                    new_items[player_name] = {}
                new_items[player_name][item] = new_items[player_name].get(item, 0) + 1
    for (p, player) in enumerate(tracker["player_checks_done"]):
        player_name = player_idx_to_name(game, p)
        locations_done = len(player["locations"])
        new_locations[player_name] = locations_done - memory[player_name]["locations"]
    
    # Send notifications according to configuration
    # use new_hints, updated_hints, new_items, new_locations, and update memory
            

if __name__ == "__main__":
    main()