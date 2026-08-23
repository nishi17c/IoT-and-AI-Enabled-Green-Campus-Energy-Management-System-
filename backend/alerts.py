"""
alerts.py — Threshold Checking & Alert Formatting
===================================================
IoT Green Campus Energy Management System

Checks incoming sensor readings against predefined safety/quality
thresholds and generates alert dicts that can be stored in the DB or
published via MQTT.

Features:
  - Configurable threshold constants at the top of the file
  - Per-node, per-alert-type cooldown to avoid alert flooding
  - ANSI colour output so alerts are visible in the console
  - format_alert_message() for human-readable strings
"""

import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANSI colour codes (works on Windows 10+ with VT mode enabled)
# ---------------------------------------------------------------------------
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_GREEN  = "\033[92m"
_CYAN   = "\033[96m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"


def _colour(text: str, code: str) -> str:
    """Wrap text with an ANSI colour code and reset."""
    return f"{code}{text}{_RESET}"


# ---------------------------------------------------------------------------
# Threshold Constants
# Adjust these to match your campus electrical specifications.
# ---------------------------------------------------------------------------
VOLTAGE_HIGH  = 250.0   # Volts  — overvoltage warning
VOLTAGE_LOW   = 200.0   # Volts  — undervoltage warning
CURRENT_HIGH  = 10.0    # Amps   — overcurrent warning
PF_LOW        = 0.80    # ratio  — poor power-factor warning
TEMP_HIGH     = 40.0    # °C     — high ambient temperature warning


# ---------------------------------------------------------------------------
# Cooldown tracking
# Structure: { "node-01|voltage_high": last_fired_timestamp, ... }
# An alert for the same node+type won't re-fire within COOLDOWN_SECONDS.
# ---------------------------------------------------------------------------
COOLDOWN_SECONDS = 60   # 1 minute between repeated alerts of the same type
_cooldown: dict[str, float] = {}


def _is_in_cooldown(node_id: str, alert_key: str) -> bool:
    """
    Return True if the (node_id, alert_key) combination fired recently
    and is still within the cooldown window.
    """
    key = f"{node_id}|{alert_key}"
    last_fired = _cooldown.get(key, 0.0)
    return (time.time() - last_fired) < COOLDOWN_SECONDS


def _set_cooldown(node_id: str, alert_key: str):
    """Record that this alert just fired for cooldown tracking."""
    key = f"{node_id}|{alert_key}"
    _cooldown[key] = time.time()


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def check_thresholds(reading: dict) -> list:
    """
    Compare a sensor reading against all configured thresholds.
    Returns a list of alert dicts for any threshold violations found.
    Only triggers if not currently in cooldown for that alert type.

    Args:
        reading (dict): A sensor reading dict (same structure as DB row).
                        Expected keys: node_id, location, voltage, current,
                        power_factor, temperature.

    Returns:
        list[dict]: Zero or more alert dicts ready to pass to insert_alert().
                    Each dict has: node_id, location, timestamp, type, message.
    """
    node_id  = reading.get("node_id", "unknown")
    location = reading.get("location", "")
    now      = datetime.now().isoformat()
    alerts   = []

    def _make_alert(alert_key: str, alert_type: str, message: str) -> dict:
        """Helper: build an alert dict and update cooldown."""
        _set_cooldown(node_id, alert_key)
        return {
            "node_id":   node_id,
            "location":  location,
            "timestamp": now,
            "type":      alert_type,
            "message":   message,
        }

    # --- Voltage High ---
    voltage = reading.get("voltage", 0.0)
    if voltage and voltage > VOLTAGE_HIGH and not _is_in_cooldown(node_id, "voltage_high"):
        msg = f"Overvoltage detected: {voltage:.1f} V (threshold: {VOLTAGE_HIGH} V)"
        alert = _make_alert("voltage_high", "error", msg)
        alerts.append(alert)
        _print_alert(alert)

    # --- Voltage Low ---
    if voltage and 0 < voltage < VOLTAGE_LOW and not _is_in_cooldown(node_id, "voltage_low"):
        msg = f"Undervoltage detected: {voltage:.1f} V (threshold: {VOLTAGE_LOW} V)"
        alert = _make_alert("voltage_low", "warn", msg)
        alerts.append(alert)
        _print_alert(alert)

    # --- Current High ---
    current = reading.get("current", 0.0)
    if current and current > CURRENT_HIGH and not _is_in_cooldown(node_id, "current_high"):
        msg = f"Overcurrent detected: {current:.2f} A (threshold: {CURRENT_HIGH} A)"
        alert = _make_alert("current_high", "error", msg)
        alerts.append(alert)
        _print_alert(alert)

    # --- Power Factor Low ---
    pf = reading.get("power_factor", 1.0)
    # Only flag PF if there is meaningful load (current > 0.1 A) to avoid false alarms
    if pf and pf < PF_LOW and reading.get("current", 0) > 0.1 and not _is_in_cooldown(node_id, "pf_low"):
        msg = f"Low power factor: {pf:.2f} (threshold: {PF_LOW}). Check capacitor bank."
        alert = _make_alert("pf_low", "warn", msg)
        alerts.append(alert)
        _print_alert(alert)

    # --- Temperature High ---
    temp = reading.get("temperature", 0.0)
    if temp and temp > TEMP_HIGH and not _is_in_cooldown(node_id, "temp_high"):
        msg = f"High temperature: {temp:.1f}°C (threshold: {TEMP_HIGH}°C) at {location or node_id}"
        alert = _make_alert("temp_high", "warn", msg)
        alerts.append(alert)
        _print_alert(alert)

    return alerts


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_alert_message(alert: dict) -> str:
    """
    Return a nicely formatted single-line string for an alert dict.

    Example output:
        [2024-01-15 14:23:05] [ERROR] node-01 (Lab A): Overvoltage detected: 255.3 V
    """
    ts       = alert.get("timestamp", datetime.now().isoformat())
    # Format ISO timestamp to a friendlier display
    try:
        dt = datetime.fromisoformat(ts)
        ts_display = dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        ts_display = ts

    alert_type = alert.get("type", "info").upper()
    node_id    = alert.get("node_id", "?")
    location   = alert.get("location", "")
    message    = alert.get("message", "")

    location_str = f" ({location})" if location else ""
    return f"[{ts_display}] [{alert_type}] {node_id}{location_str}: {message}"


def _print_alert(alert: dict):
    """
    Print a colour-coded alert to the console.
      - ERROR → red
      - WARN  → yellow
      - INFO  → cyan
      - OK    → green
    """
    formatted = format_alert_message(alert)
    alert_type = alert.get("type", "info").lower()

    colour_map = {
        "error": _RED,
        "warn":  _YELLOW,
        "info":  _CYAN,
        "ok":    _GREEN,
    }
    colour = colour_map.get(alert_type, _RESET)

    prefix_map = {
        "error": "🔴 ALERT",
        "warn":  "🟡 WARN ",
        "info":  "🔵 INFO ",
        "ok":    "🟢 OK   ",
    }
    prefix = prefix_map.get(alert_type, "   ")

    print(_colour(f"{prefix} | {formatted}", colour))
    logger.log(
        logging.ERROR if alert_type == "error" else logging.WARNING,
        "Alert [%s] %s", alert_type.upper(), formatted
    )
