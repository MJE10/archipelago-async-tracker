import subprocess
import os

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
        print(result.stdout)
        print('---')
        print(result.stderr)
        items = []

        if "In logic list:" in stdout:
            parts = stdout.split("In logic list:")
            raw_list = parts[1].strip().splitlines()
            items = [line.strip() for line in raw_list if line.strip()]

        return items

    except subprocess.CalledProcessError as e:
        print(f"Error running Docker: {e.stderr}")
        return []


# --- Usage Example ---
if __name__ == "__main__":
    path_to_players = "/home/michael/sync/ap/async-tracker/logic_tracker/Players"
    name = "MJE10_celeste"

    logic_list = get_logic_items(path_to_players, name)

    print(f"Found {len(logic_list)} items in logic:")
    for item in logic_list:
        print(f" - {item}")
