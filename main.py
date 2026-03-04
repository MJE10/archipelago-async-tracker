import yaml
from util import *

def main():
    with open("games.yaml", 'r') as f:
        games = yaml.load(f, Loader=yaml.SafeLoader)
    
    for game in games:
        games[game]["name"] = game
        process_game(game, games[game])

def process_game(name, game):
    print(f"Now processing: {name}")

    for idx in range(len(room_status(game)['players'])):
        datapackage(game, idx)

    fetch_tracker(game)

if __name__ == "__main__":
    main()