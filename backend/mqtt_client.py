"""
mqtt_client.py — MQTT Subscriber & Publisher
=============================================
IoT Green Campus Energy Management System

Subscribes to the campus/# wildcard topic using paho-mqtt.
Handles incoming JSON payloads from ESP8266 NodeMCU nodes and routes
them to the appropriate database functions.

Topic routing:
  campus/+/energy      → insert_reading()
  campus/+/environment → merge env data into latest reading and update
  campus/+/status      → upsert_node_status()
  campus/+/alert       → insert_alert()
  campus/+/relay       → (outbound only, used to control relay)

The module-level dict `latest_data` always holds the most recent
combined reading per node_id so the REST API and WebSocket can serve
live data without hitting the database every time.
"""

import json
import logging
import threading
import time
from datetime import datetime
from typing import Optional

import paho.mqtt.client as mqtt

import database

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MQTT Configuration
# ---------------------------------------------------------------------------
MQTT_HOST      = "broker.emqx.io"
MQTT_PORT      = 1883
MQTT_CLIENT_ID = "ems-backend"
MQTT_KEEPALIVE = 60          # seconds between ping packets
RECONNECT_DELAY = 5          # seconds to wait before reconnect attempt

# ---------------------------------------------------------------------------
# In-memory store for the latest combined reading per node
# Access with get_latest_data() to avoid direct dict mutation from outside
# ---------------------------------------------------------------------------
latest_data: dict[str, dict] = {}
_data_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Module-level MQTT client (singleton)
# ---------------------------------------------------------------------------
_client: Optional[mqtt.Client] = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_topic(topic: str):
    """
    Split an MQTT topic string into (node_id, subtopic).

    Example:
        "campus/node-01/energy" → ("node-01", "energy")
        "campus/node-01/status" → ("node-01", "status")

    Returns (None, None) if the topic format is unexpected.
    """
    parts = topic.split("/")
    if len(parts) == 3 and parts[0] == "campus":
        return parts[1], parts[2]
    return None, None


def _update_latest(node_id: str, data: dict):
    """Merge `data` into latest_data[node_id] in a thread-safe way."""
    with _data_lock:
        if node_id not in latest_data:
            latest_data[node_id] = {}
        latest_data[node_id].update(data)
        # Always stamp the merge time
        latest_data[node_id]["last_updated"] = datetime.now().isoformat()


# ---------------------------------------------------------------------------
# MQTT Callbacks
# ---------------------------------------------------------------------------

def _on_connect(client, userdata, flags, rc):
    """Called when the client connects (or reconnects) to the broker."""
    if rc == 0:
        logger.info("MQTT connected to %s:%s", MQTT_HOST, MQTT_PORT)
        # Subscribe to the wildcard — receives ALL campus messages
        client.subscribe("campus/#", qos=1)
        logger.info("Subscribed to campus/#")
    else:
        # rc codes: 1=bad protocol, 2=client id rejected, 3=server unavailable
        # 4=bad credentials, 5=not authorised
        logger.error("MQTT connection refused — return code %d", rc)


def _on_disconnect(client, userdata, rc):
    """Called on disconnect. Paho will auto-reconnect if loop_forever() is used."""
    if rc != 0:
        logger.warning("MQTT unexpectedly disconnected (rc=%d). Reconnecting…", rc)
    # With loop_forever() paho handles reconnection internally.
    # The delay below prevents a tight reconnect storm if the broker is down.
    time.sleep(RECONNECT_DELAY)


def _on_message(client, userdata, msg):
    """
    Dispatch incoming MQTT messages to the correct handler based on subtopic.
    All payloads are expected to be valid UTF-8 encoded JSON objects.
    """
    topic   = msg.topic
    payload = msg.payload.decode("utf-8", errors="replace")

    node_id, subtopic = _parse_topic(topic)
    if node_id is None:
        logger.debug("Ignoring unexpected topic: %s", topic)
        return

    # --- Parse JSON payload ---
    try:
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("Payload is not a JSON object")
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Bad JSON on topic '%s': %s | payload: %s", topic, e, payload[:200])
        return

    # Inject node_id so handlers don't need to re-parse the topic
    data["node_id"] = node_id

    # --- Route to handler ---
    if subtopic == "energy":
        _handle_energy(node_id, data)
    elif subtopic == "environment":
        _handle_environment(node_id, data)
    elif subtopic == "status":
        _handle_status(node_id, data)
    elif subtopic == "alert":
        _handle_alert(node_id, data)
    else:
        logger.debug("No handler for subtopic '%s' (node: %s)", subtopic, node_id)


# ---------------------------------------------------------------------------
# Topic Handlers
# ---------------------------------------------------------------------------

def _handle_energy(node_id: str, data: dict):
    """
    Process campus/{node_id}/energy messages.
    Stores the reading in the DB and updates the in-memory cache.

    Expected payload keys (all optional — defaults to 0):
        voltage, current, power_kw, energy_kwh, session_kwh,
        frequency, power_factor, relay_state, location, timestamp
    """
    # Add server-side timestamp if the node didn't send one
    if "timestamp" not in data:
        data["timestamp"] = datetime.now().isoformat()

    logger.debug("Energy from %s: %.2f kW, %.2f V", node_id, data.get("power_kw", 0), data.get("voltage", 0))

    database.insert_reading(data)
    _update_latest(node_id, data)

    # Check thresholds and auto-generate alerts
    try:
        import alerts as alert_module
        triggered = alert_module.check_thresholds(data)
        for alert in triggered:
            database.insert_alert(alert)
            _update_latest(node_id, {"last_alert": alert.get("message", "")})
    except Exception as e:
        logger.error("Alert check failed for node '%s': %s", node_id, e)


def _handle_environment(node_id: str, data: dict):
    """
    Process campus/{node_id}/environment messages.
    Merges temperature, humidity, motion, light_pct into the node's
    latest reading so the dashboard shows a unified record.

    Expected payload keys:
        temperature, humidity, motion (0/1), light_pct (0-100)
    """
    env_fields = {
        "temperature": data.get("temperature", 0.0),
        "humidity":    data.get("humidity", 0.0),
        "motion":      int(data.get("motion", 0)),
        "light_pct":   data.get("light_pct", 0.0),
        "node_id":     node_id,
    }

    logger.debug("Environment from %s: %.1f°C, %.1f%% RH, motion=%s",
                 node_id, env_fields["temperature"], env_fields["humidity"], bool(env_fields["motion"]))

    _update_latest(node_id, env_fields)

    # If we already have a recent energy reading for this node,
    # merge env data and write a combined reading row to the DB
    with _data_lock:
        combined = dict(latest_data.get(node_id, {}))

    if combined.get("voltage") or combined.get("power_kw"):
        combined.update(env_fields)
        combined["timestamp"] = datetime.now().isoformat()
        database.insert_reading(combined)


def _handle_status(node_id: str, data: dict):
    """
    Process campus/{node_id}/status messages.
    Updates the node_status table and in-memory cache.

    Expected payload keys:
        location, status, ip, rssi, uptime, relay
    """
    data["last_seen"] = datetime.now().isoformat()

    logger.info("Status from %s: %s (IP: %s, RSSI: %s dBm)",
                node_id, data.get("status", "?"), data.get("ip", "?"), data.get("rssi", "?"))

    database.upsert_node_status(data)
    _update_latest(node_id, {
        "status":    data.get("status", "online"),
        "ip":        data.get("ip", ""),
        "rssi":      data.get("rssi", 0),
        "uptime":    data.get("uptime", 0),
        "relay":     data.get("relay", 0),
        "last_seen": data["last_seen"],
    })


def _handle_alert(node_id: str, data: dict):
    """
    Process campus/{node_id}/alert messages sent directly by the ESP8266.
    Stores alert in the DB.

    Expected payload keys:
        type (error/warn/info/ok), message, location (optional)
    """
    data["timestamp"] = data.get("timestamp", datetime.now().isoformat())

    logger.warning("ALERT from %s [%s]: %s", node_id, data.get("type", "info"), data.get("message", ""))

    database.insert_alert(data)
    _update_latest(node_id, {"last_alert": data.get("message", "")})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_latest_data() -> dict:
    """
    Return a snapshot of the in-memory latest_data dict.
    Thread-safe copy so callers can iterate without a lock.

    Returns:
        dict: {node_id: {combined reading fields}, ...}
    """
    with _data_lock:
        return dict(latest_data)


def publish_relay_command(node_id: str, command: str):
    """
    Publish a relay control command to campus/{node_id}/relay.

    Args:
        node_id (str): Target node identifier.
        command (str): One of 'on', 'off', or 'toggle'.

    The ESP8266 listens on this topic and toggles the relay accordingly.
    """
    if _client is None:
        logger.error("Cannot publish — MQTT client not initialised")
        return

    topic   = f"campus/{node_id}/relay"
    # Send plain command string ("on", "off", "toggle") for direct firmware string match
    payload = command.lower()

    result = _client.publish(topic, payload, qos=1, retain=False)
    if result.rc == mqtt.MQTT_ERR_SUCCESS:
        logger.info("Relay command '%s' sent to %s", command, node_id)
    else:
        logger.error("Failed to publish relay command to %s (rc=%d)", node_id, result.rc)


def start_mqtt_thread(broker="broker.emqx.io", port=1883):
    """
    Initialise the paho-mqtt client and start the network loop in a
    background daemon thread.  Call once from server startup.

    The daemon thread will automatically die when the main process exits.
    """
    global _client

    _client = mqtt.Client(client_id=MQTT_CLIENT_ID, clean_session=True)
    _client.on_connect    = _on_connect
    _client.on_disconnect = _on_disconnect
    _client.on_message    = _on_message

    # Attempt initial connection (non-blocking — retries via on_disconnect)
    try:
        _client.connect(MQTT_HOST, MQTT_PORT, keepalive=MQTT_KEEPALIVE)
        logger.info("Connecting to MQTT broker at %s:%s…", MQTT_HOST, MQTT_PORT)
    except Exception as e:
        logger.error("Initial MQTT connect failed: %s. Will retry in background.", e)

    # loop_start() runs the network loop in a daemon thread
    _client.loop_start()
    logger.info("MQTT background thread started.")
