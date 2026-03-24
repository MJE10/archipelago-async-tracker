# Project Guide: Archipelago Async Tracker

This guide provides an overview of the Archipelago Async Tracker project, its architecture, and how to work with it.

## 1. Project Overview

The Archipelago Async Tracker is a web-based application designed to track the progress of Archipelago multiworld games asynchronously. It uses a Flask backend to serve game data and a custom logic tracker running in a Docker container to determine "in-logic" items for players. This allows users to monitor game progress and item logic without needing to run the Archipelago client continuously.

*   **Purpose:** To provide an asynchronous tracking solution for Archipelago multiworld games.
*   **Key Technologies:** Python (Flask, Redis, Docker), JavaScript/HTML/CSS (for the frontend, served by Flask).
*   **High-level Architecture:**
    *   **Frontend:** A simple web interface served by Flask (`static/index.html`).
    *   **Backend (Python/Flask):**
        *   Exposes API endpoints for game data, refreshing specific trackers, and triggering a full refresh.
        *   Manages a background thread that periodically updates game data by interacting with the Archipelago API and the custom logic tracker.
        *   Uses Redis as a cache for API responses and expensive logic calculations.
    *   **Logic Tracker (Python/Docker):**
        *   A Dockerized environment that runs a modified Archipelago Custom Tracker.
        *   Takes player item and location data as input.
        *   Outputs a list of items currently "in logic" for a given player.

## 2. Getting Started

### Prerequisites

*   **Docker:** Required to build and run the Archipelago Custom Tracker.
*   **Python 3.8+:** For the Flask application and utility scripts.
*   **Redis:** A running Redis instance for caching. (The current configuration points to `100.109.133.47:6379`, this may need to be updated).

### Installation Instructions

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd <repository_name>
    ```
2.  **Set up Redis:**
    Ensure a Redis server is accessible at the configured host and port (default in `util.py` is `100.109.133.47:6379`). You might need to adjust this in `util.py`.
3.  **Build the Logic Tracker Docker Image:**
    Navigate to the `logic_tracker` directory and build the Docker image:
    ```bash
    cd logic_tracker
    docker build --pull --rm -f 'logic_tracker/Dockerfile' -t 'asynctracker:latest' .
    cd ..
    ```
4.  **Install Python Dependencies:**
    It is recommended to use a virtual environment:
    ```bash
    python -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt # (assuming a requirements.txt exists or create one based on imports)
    ```
    *Note: A `requirements.txt` file is not explicitly present in the provided context, but `main.py` and `util.py` import `Flask`, `PyYAML`, `redis`, `requests`, so these would be the initial requirements.*
5.  **Configure Games:**
    Edit the `games.yaml` file to define the Archipelago games you want to track, including their `link`, `players`, and `password`.

### Basic Usage Examples

1.  **Run the Flask application:**
    ```bash
    python main.py
    ```
    The application will be accessible at `http://0.0.0.0:5151`.
2.  **Access the web interface:**
    Open `http://localhost:5151` in your browser.
3.  **Trigger a tracker refresh via API:**
    ```
    GET http://localhost:5151/refresh_tracker/<game_name>
    ```
4.  **Trigger a full refresh of all games:**
    ```
    GET http://localhost:5151/refresh_all
    ```
5.  **Trigger a super refresh (clears all cached data for a game):**
    ```
    GET http://localhost:5151/super_refresh/<game_name>
    ```

### Running Tests

(Assuming there are no explicit test files provided, this section is a placeholder.)

Currently, there are no dedicated test scripts or framework configured. Manual testing involves:
*   Verifying the Flask API endpoints.
*   Checking the `logic_tracker`'s output for correctness.
*   Monitoring Redis cache behavior.

## 3. Project Structure

*   `.git/`: Git version control metadata.
*   `.gitignore`: Specifies intentionally untracked files to ignore.
*   `.python-version`: Specifies the Python version used (e.g., `3.12`).
*   `acked.json`: (Purpose unknown, likely internal to Continue or a development artifact).
*   `main.py`: The main Flask application entry point. Handles web routes and the background update loop.
*   `memory.json`: (Currently commented out in `main.py`, but seems intended for persistent memory/state between runs).
*   `static/`: Contains static files for the web frontend.
    *   `static/index.html`: The main HTML file for the web interface.
*   `util.py`: Utility functions for API interactions, Redis caching, and orchestrating logic calculations.
*   `games.yaml`: Configuration file for defining Archipelago games to be tracked.
*   `logic_tracker/`: Directory containing the Archipelago Custom Tracker logic and Docker setup.
    *   `logic_tracker/Dockerfile`: Dockerfile for building the `asynctracker` image.
    *   `logic_tracker/in_container.py`: (Not explicitly reviewed, but likely a script run inside the Docker container).
    *   `logic_tracker/run_logic.py`: Script responsible for running the Dockerized Archipelago Custom Tracker and parsing its output.
    *   `logic_tracker/README.txt`: Contains Docker build commands.
    *   `logic_tracker/Players/`: Directory for Archipelago player YAML files. (e.g., `MJE10_celeste_2h.yaml`).
    *   `logic_tracker/world/`: Contains Archipelago world definition files for the custom tracker.
        *   `logic_tracker/world/TrackerClient.py`: Part of the Archipelago client logic.
        *   `logic_tracker/world/TrackerCore.py`: Core logic for the Archipelago tracker.
        *   `logic_tracker/world/__init__.py`: Python package initializer.
        *   `logic_tracker/world/archipelago.json`: (Purpose unknown, likely Archipelago-related configuration).
        *   `logic_tracker/world/icon.png`: Icon file.

## 4. Development Workflow

### Coding Standards or Conventions

*   **Python:** Follows generally accepted Python best practices (e.g., PEP 8 for style).
*   **Flask:** Standard Flask application structure.
*   **Archipelago API:** Interactions with the Archipelago API should be done through the utility functions in `util.py` to leverage caching.

### Testing Approach

(Placeholder - needs definition based on team practices)
*   **Unit Tests:** Implement unit tests for functions in `util.py` and `logic_tracker/run_logic.py`.
*   **Integration Tests:** Test the interaction between the Flask app, Redis, and the Dockerized logic tracker.
*   **End-to-End Tests:** Verify the full functionality from the web UI to the logic calculation.

### Build and Deployment Process

*   **Logic Tracker:** Built using Docker (as shown in `logic_tracker/README.txt`). The image (`asynctracker:latest`) is then used by `run_logic.py`.
*   **Flask Application:** The Flask application (`main.py`) is run directly as a Python script. For production, it would typically be deployed with a WSGI server (e.g., Gunicorn, uWSGI) and a reverse proxy (e.g., Nginx, Apache).

### Contribution Guidelines

(Placeholder - needs definition based on team practices)
1.  Fork the repository.
2.  Create a new feature branch (`git checkout -b feature/your-feature-name`).
3.  Implement your changes, following existing coding conventions.
4.  Write or update tests as appropriate.
5.  Ensure all tests pass.
6.  Commit your changes (`git commit -m 'feat: Add new feature'`).
7.  Push to your branch (`git push origin feature/your-feature-name`).
8.  Open a Pull Request.

## 5. Key Concepts

*   **Archipelago Multiworld:** A system that connects multiple players across different games into a single "multiworld," where items for one player's game might be found in another player's game.
*   **Custom Tracker:** A client-side tool provided by Archipelago that can determine which items are currently "in logic" (i.e., discoverable with current inventory) for a player.
*   **Redis Caching:** Used to store results from expensive API calls and logic calculations to improve performance and reduce load on external services.
*   **"In Logic" Items:** Items that are currently discoverable by a player given their current inventory and game state, according to the game's logic.

## 6. Common Tasks

### Adding a New Game to Track

1.  Open `games.yaml`.
2.  Add a new entry with a unique game name.
3.  Specify the `link` to the Archipelago room, `players` in that room, and `password` if required.
4.  Restart the `main.py` Flask application for the changes to take effect.

### Clearing Cache for a Game

To force a full re-fetch and re-calculation for a specific game:
*   Use the `/super_refresh/<game_name>` API endpoint.

### Debugging Logic Calculation

1.  Temporarily add `print()` statements within `logic_tracker/run_logic.py`, `util.py`, `logic_tracker/world/TrackerCore.py` and `logic_tracker/world/TrackerClient.py` to inspect intermediate data.
2.  Run the Flask application and trigger the specific game's refresh.
3.  Examine the console output.

## 7. Troubleshooting

*   **"Error running Docker"**:
    *   Ensure Docker is installed and running correctly.
    *   Verify the `asynctracker:latest` Docker image was built successfully (`docker images`).
    *   Check the `logic_tracker/Dockerfile` for any build errors.
    *   Ensure proper volume mounts are configured in `run_logic.py` (e.g., `/app/Archipelago/Players`).
*   **Redis Connection Errors:**
    *   Verify the Redis server is running and accessible from the machine hosting the Flask application.
    *   Check the `host` and `port` in `util.py`'s `redis.Redis` client initialization.
*   **Incorrect Logic Output:**
    *   Inspect the `items_received.json` and `missing_checks.json` files generated in the temporary directory during `calculate_trackers` in `util.py` to ensure correct data is being passed to `run_logic.py`.
    *   Examine the output of the `get_logic_items` call in `run_logic.py` for any errors from the Archipelago Custom Tracker.
    *   Verify that player YAML files are correctly placed in `logic_tracker/Players/`.
*   **Frontend Not Updating:**
    *   Check the browser's developer console for JavaScript errors.
    *   Verify that the `/games` API endpoint is returning the expected JSON data.
    *   Ensure the `background_update_loop` in `main.py` is running and not encountering exceptions.

## 8. References

*   **Archipelago Multiworld Documentation:** [https://archipelago.gg/](https://archipelago.gg/)
*   **Flask Documentation:** [https://flask.palletsprojects.com/](https://flask.palletsprojects.com/)
*   **Redis Documentation:** [https://redis.io/docs/](https://redis.io/docs/)
*   **Docker Documentation:** [https://docs.docker.com/](https://docs.docker.com/)
