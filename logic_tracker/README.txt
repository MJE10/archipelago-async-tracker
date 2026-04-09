docker build --pull --rm -f 'logic_tracker/Dockerfile' -t 'asynctracker:latest' 'logic_tracker'
docker build --no-cache -t asynctracker:latest .

docker run --rm -v /home/michael/sync/ap/async-tracker/logic_tracker/Players:/opt/Archipelago/Players -v /home/michael/sync/ap/async-tracker/custom_worlds:/opt/Archipelago/custom_worlds asynctracker:latest python3 /opt/Archipelago/in_container.py --name jigsaw