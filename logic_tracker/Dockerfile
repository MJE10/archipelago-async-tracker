FROM python:3.12-slim-bookworm

# 1. Install System Dependencies
# Includes build tools for ModuleUpdate/speedups and 
# graphics libs to satisfy Kivy's import checks.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    zip \
    curl \
    gcc \
    g++ \
    python3-dev \
    libgl1 \
    libmtdev1 \
    libglib2.0-0 \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Clone the repository
RUN git clone https://github.com/ArchipelagoMW/Archipelago.git Archipelago

WORKDIR /app/Archipelago

# 3. Install Python requirements
# We install these first to ensure ModuleUpdate has what it needs to run.
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r WebHostLib/requirements.txt && \
    pip install --no-cache-dir "setuptools>=75,<81" "cx-Freeze==8.4.0" Cython

# 4. Run ModuleUpdate
# This is kept as requested to ensure all sub-dependencies are pulled in.
RUN python ModuleUpdate.py -y

# 5. Compile the Speedups
# Running this after ModuleUpdate to ensure all logic-heavy components are optimized.
RUN python setup.py build_ext --inplace

# 6. Handle the 'world' folder
# Copying the host's 'world' folder directly into the custom_tracker directory.
COPY world /app/Archipelago/worlds/custom_tracker

# 7. Setup Volumes and Environment
VOLUME ["/app/Archipelago/Players"]
VOLUME ["/app/Archipelago/custom_worlds"]

# Prevents Kivy from trying to spawn a window and keeps the logs clean.
ENV KIVY_NO_CONSOLELOG=1
ENV KIVY_NO_FILELOG=1
ENV KIVY_NO_ARGS=1
ENV SKIP_REQUIREMENTS_UPDATE=true

CMD ["/bin/bash"]