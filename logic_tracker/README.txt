docker build --pull --rm -f 'logic_tracker/Dockerfile' -t 'asynctracker:latest' 'logic_tracker'
docker build --no-cache -t asynctracker:latest .