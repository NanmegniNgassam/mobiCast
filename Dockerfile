FROM python:3.11-slim

# Set a non-root working directory
WORKDIR /app

# Install Python dependencies before copying source to leverage layer cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Create runtime directories that will be overlaid by Docker volumes
RUN mkdir -p /app/data/analyses /app/data/defaults /app/data/tmp /app/db

EXPOSE 8050

# Use gunicorn in production; 2 workers is sufficient for a local single-user tool
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:8050", "app:server"]
