FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY mqtt_bridge/requirements.txt ./mqtt_bridge/
RUN pip install --no-cache-dir -r mqtt_bridge/requirements.txt

# Copy application code
COPY custom_components/pushok_hub/api ./custom_components/pushok_hub/api/
COPY custom_components/pushok_hub/__init__.py ./custom_components/pushok_hub/
COPY custom_components/pushok_hub/const.py ./custom_components/pushok_hub/
COPY mqtt_bridge ./mqtt_bridge/

# Run the bridge
CMD ["python", "-m", "mqtt_bridge"]
