FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies before copying source to leverage layer cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source (reference files are excluded via .dockerignore)
COPY . .

# Copy entrypoint script to a system-level path and make it executable
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create required runtime directories
RUN mkdir -p /app/data/defaults /app/data/analyses /app/data/tmp /app/db

EXPOSE 8050

ENTRYPOINT ["/entrypoint.sh"]
