FROM debian:bookworm-slim

# System Python for in_container.py + curl for downloading AP release
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    xauth \
    libgl1-mesa-dri \
    libgl1-mesa-glx \
    libsdl2-2.0-0 \
    python3 \
    python3-pip \
    curl \
    libgl1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# websocket-client needed by in_container.py
RUN pip3 install websocket-client --break-system-packages

# Download and extract official Archipelago 0.6.6 binary release
RUN curl -L https://github.com/ArchipelagoMW/Archipelago/releases/download/0.6.7/Archipelago_0.6.7_linux-x86_64.tar.gz \
    -o /tmp/ap.tar.gz \
    && mkdir -p /opt/Archipelago \
    && tar -xzf /tmp/ap.tar.gz -C /opt/Archipelago --strip-components=1 \
    && rm /tmp/ap.tar.gz

# Prevents Kivy from trying to spawn a window
ENV LIBGL_ALWAYS_SOFTWARE=1
ENV DISPLAY=:99
ENV KIVY_NO_CONSOLELOG=1
ENV KIVY_NO_FILELOG=1
ENV KIVY_NO_ARGS=1
ENV SKIP_REQUIREMENTS_UPDATE=true
ENV SDL_VIDEODRIVER=offscreen
ENV SDL_AUDIODRIVER=dummy
# ENV KIVY_WINDOW=dummy
# ENV KIVY_TEXT=pil
# ENV KIVY_IMAGE=pil

COPY in_container.py /opt/Archipelago/in_container.py

VOLUME ["/opt/Archipelago/Players"]
VOLUME ["/opt/Archipelago/custom_worlds"]

CMD ["/bin/bash"]
