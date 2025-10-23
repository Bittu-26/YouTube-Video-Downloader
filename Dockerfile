# 1. Start with a Python base image (Debian-based, so apt works)
FROM python:3.11-slim

# 2. Install the FFMPEG system binary
#    Update package list, install ffmpeg, and clean up package cache
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# 3. Set the working directory
WORKDIR /usr/src/app

# 4. Copy and install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of the application code
COPY . .


# 6. Define the command to run the application using Gunicorn
#    Gunicorn runs the application defined in the 'server' module (server.py) 
#    and the Flask instance 'app'.
CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "server:app"]
