import json
import os
import threading
import requests
from datetime import datetime, timezone

NOTIFICATIONS_FILE = "notifications.json"
NTFY_TOPIC = "https://ntfy.sh/mj_ap_async_provide_smile"

_lock = threading.Lock()
_first_run = True


def _parse_dt(s):
    if not s:
        return None
    try:
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _load():
    if not os.path.exists(NOTIFICATIONS_FILE):
        return {"subscriptions": {}}
    with open(NOTIFICATIONS_FILE, 'r') as f:
        return json.load(f)


def _save(data):
    with open(NOTIFICATIONS_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def get_active_subscriptions():
    """Returns {game_name: {player_name: {expires_at}}} for non-expired subs only."""
    with _lock:
        data = _load()
    now = datetime.now(timezone.utc)
    result = {}
    for game_name, players in data.get("subscriptions", {}).items():
        for player_name, sub in players.items():
            exp = _parse_dt(sub.get("expires_at"))
            if exp and exp > now:
                result.setdefault(game_name, {})[player_name] = {
                    "expires_at": sub["expires_at"]
                }
    return result


def update_subscriptions(new_subs, current_logic):
    """
    Replace entire subscription config.
    new_subs: {game_name: {player_name: "ISO_expires_at"}} — omit/None to clear.
    current_logic: {game_name: {player_name: [in_logic list]}} — always used as new baseline.
    """
    with _lock:
        new_data = {"subscriptions": {}}
        for game_name, players in new_subs.items():
            for player_name, expires_at in players.items():
                if not expires_at:
                    continue
                # Always reset baseline to current in_logic (per user spec)
                seen_logic = list(current_logic.get(game_name, {}).get(player_name, []))
                new_data["subscriptions"].setdefault(game_name, {})[player_name] = {
                    "expires_at": expires_at,
                    "seen_logic": seen_logic,
                }
        _save(new_data)


def check_and_notify(all_game_results):
    """Check subscribed players for new in-logic checks; send one consolidated notification."""
    global _first_run

    # Skip the very first run after startup to avoid spurious notifications
    if _first_run:
        _first_run = False
        # Still update seen_logic to current state so we baseline correctly
        with _lock:
            data = _load()
            subs = data.get("subscriptions", {})
            now = datetime.now(timezone.utc)
            changed = False
            for game_name, players in subs.items():
                for player_name, sub in players.items():
                    exp = _parse_dt(sub.get("expires_at"))
                    if not exp or exp <= now:
                        continue
                    seen_logic = set(sub.get("seen_logic", []))
                    player_data = (
                        all_game_results.get(game_name, {})
                        .get("players", {})
                        .get(player_name, {})
                    )
                    current_logic = set(player_data.get("in_logic", []))
                    updated_seen = current_logic | seen_logic
                    if updated_seen != seen_logic:
                        subs[game_name][player_name]["seen_logic"] = list(updated_seen)
                        changed = True
            if changed:
                _save(data)
        return

    new_notifications = []

    with _lock:
        data = _load()
        subs = data.get("subscriptions", {})
        now = datetime.now(timezone.utc)
        changed = False

        for game_name, players in subs.items():
            for player_name, sub in players.items():
                exp = _parse_dt(sub.get("expires_at"))
                if not exp or exp <= now:
                    continue

                seen_logic = set(sub.get("seen_logic", []))
                player_data = (
                    all_game_results.get(game_name, {})
                    .get("players", {})
                    .get(player_name, {})
                )
                current_logic = set(player_data.get("in_logic", []))

                new_checks = current_logic - seen_logic
                if new_checks:
                    new_notifications.append((player_name, len(new_checks)))

                updated_seen = current_logic | seen_logic
                if updated_seen != seen_logic:
                    subs[game_name][player_name]["seen_logic"] = list(updated_seen)
                    changed = True

        if changed:
            _save(data)

    if new_notifications:
        total = sum(c for _, c in new_notifications)
        parts = ", ".join(f"{p} ({c} new)" for p, c in new_notifications)
        message = f"{total} new check{'s' if total != 1 else ''} in logic: {parts}"
        _send_ntfy("New Logic Checks", message)


def _send_ntfy(title, message):
    try:
        requests.post(
            NTFY_TOPIC,
            data=message.encode("utf-8"),
            headers={"Title": title},
            timeout=10,
        )
        print(f"ntfy sent: {title} — {message}")
    except Exception as e:
        print(f"ntfy error: {e}")
