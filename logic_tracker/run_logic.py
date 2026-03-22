import subprocess
import os

def get_logic_items(players_path, player_name, image_tag="asynctracker:latest"):
    """
    Runs the Archipelago Docker container, executes the Custom Tracker,
    and returns a list of items found after 'In logic list:'.
    """
    
    # Construct the docker command
    # We use --rm to clean up the container automatically after it finishes
    docker_cmd = [
        "docker", "run", "--rm", "--network", "none",
        "-v", f"{os.path.abspath(players_path)}:/app/Archipelago/Players",
        image_tag,
        "python", "Launcher.py", "Custom Tracker", "--", 
        "--list", "--name", player_name, "--nogui"
    ]

    try:
        # Execute and capture stdout
        result = subprocess.run(
            docker_cmd, 
            capture_output=True, 
            text=True, 
            check=True
        )
        
        stdout = result.stdout
        items = []
        
        # Parse the output
        if "In logic list:" in stdout:
            # Split by the trigger phrase and take everything after it
            parts = stdout.split("In logic list:")
            # The list items follow the phrase, usually one per line
            raw_list = parts[1].strip().splitlines()
            
            # Clean up whitespace and ignore empty lines
            items = [line.strip() for line in raw_list if line.strip()]
            
        return items

    except subprocess.CalledProcessError as e:
        print(f"Error running Docker: {e.stderr}")
        return []

# --- Usage Example ---
if __name__ == "__main__":
    # Update this path to your local Players folder
    path_to_players = "/home/michael/sync/ap/async-tracker/logic_tracker/Players"
    name = "MJE10_celeste"
    
    logic_list = get_logic_items(path_to_players, name)
    
    print(f"Found {len(logic_list)} items in logic:")
    for item in logic_list:
        print(f" - {item}")