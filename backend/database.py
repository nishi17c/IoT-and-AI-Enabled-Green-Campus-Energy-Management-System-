"""
database.py — SQLite Database Module
=====================================
IoT Green Campus Energy Management System
Handles all database operations using Python's built-in sqlite3.

Tables:
  - readings    : Sensor readings (power, energy, environment)
  - alerts      : System alerts and warnings
  - node_status : Real-time status of each IoT node

Thread-safety is achieved via a threading.Lock() that wraps every
database operation so concurrent MQTT callbacks and API requests don't
corrupt the database.
"""

import sqlite3
import threading
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_PATH = "campus_ems.db"          # SQLite database file path

# A single module-level lock ensures only one thread touches the DB at a time
_db_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_connection() -> sqlite3.Connection:
    """Open and return a SQLite connection with row_factory set to dict-like."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row   # Allows column access by name
    conn.execute("PRAGMA journal_mode=WAL;")  # Improves concurrent read perf
    return conn


def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row object to a plain Python dict."""
    return dict(row) if row else {}


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init_db():
    """
    Create all required tables if they don't already exist.
    Call this once at application startup before any other DB operation.
    """
    create_readings = """
    CREATE TABLE IF NOT EXISTS readings (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        node_id     TEXT    NOT NULL,
        location    TEXT    DEFAULT '',
        timestamp   TEXT    NOT NULL,
        voltage     REAL    DEFAULT 0.0,
        current     REAL    DEFAULT 0.0,
        power_kw    REAL    DEFAULT 0.0,
        energy_kwh  REAL    DEFAULT 0.0,
        session_kwh REAL    DEFAULT 0.0,
        frequency   REAL    DEFAULT 50.0,
        power_factor REAL   DEFAULT 1.0,
        temperature REAL    DEFAULT 0.0,
        humidity    REAL    DEFAULT 0.0,
        motion      INTEGER DEFAULT 0,
        light_pct   REAL    DEFAULT 0.0,
        relay_state INTEGER DEFAULT 0
    );
    """

    create_alerts = """
    CREATE TABLE IF NOT EXISTS alerts (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        node_id   TEXT NOT NULL,
        location  TEXT DEFAULT '',
        timestamp TEXT NOT NULL,
        type      TEXT NOT NULL CHECK(type IN ('error','warn','info','ok')),
        message   TEXT NOT NULL
    );
    """

    create_node_status = """
    CREATE TABLE IF NOT EXISTS node_status (
        node_id   TEXT PRIMARY KEY,
        location  TEXT DEFAULT '',
        status    TEXT DEFAULT 'offline',
        ip        TEXT DEFAULT '',
        rssi      INTEGER DEFAULT 0,
        uptime    INTEGER DEFAULT 0,
        relay     INTEGER DEFAULT 0,
        last_seen TEXT DEFAULT ''
    );
    """

    create_index = """
    CREATE INDEX IF NOT EXISTS idx_readings_node_ts
        ON readings (node_id, timestamp DESC);
    """

    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(create_readings)
            conn.execute(create_alerts)
            conn.execute(create_node_status)
            conn.execute(create_index)
            conn.commit()
            logger.info("Database initialised at '%s'", DB_PATH)
        except sqlite3.Error as e:
            logger.error("Failed to initialise database: %s", e)
            raise
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# INSERT / UPSERT operations
# ---------------------------------------------------------------------------

def insert_reading(data: dict):
    """
    Insert a sensor reading row into the readings table.

    Args:
        data (dict): Must contain at minimum 'node_id' and 'timestamp'.
                     Any missing numeric fields default to 0.
    """
    sql = """
    INSERT INTO readings
        (node_id, location, timestamp, voltage, current, power_kw,
         energy_kwh, session_kwh, frequency, power_factor,
         temperature, humidity, motion, light_pct, relay_state)
    VALUES
        (:node_id, :location, :timestamp, :voltage, :current, :power_kw,
         :energy_kwh, :session_kwh, :frequency, :power_factor,
         :temperature, :humidity, :motion, :light_pct, :relay_state)
    """
    row = {
        "node_id":      data.get("node_id", "unknown"),
        "location":     data.get("location", ""),
        "timestamp":    data.get("timestamp", datetime.now().isoformat()),
        "voltage":      data.get("voltage", 0.0),
        "current":      data.get("current", 0.0),
        "power_kw":     data.get("power_kw", 0.0),
        "energy_kwh":   data.get("energy_kwh", 0.0),
        "session_kwh":  data.get("session_kwh", 0.0),
        "frequency":    data.get("frequency", 50.0),
        "power_factor": data.get("power_factor", 1.0),
        "temperature":  data.get("temperature", 0.0),
        "humidity":     data.get("humidity", 0.0),
        "motion":       int(data.get("motion", 0)),
        "light_pct":    data.get("light_pct", 0.0),
        "relay_state":  int(data.get("relay_state", 0)),
    }

    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(sql, row)
            conn.commit()
        except sqlite3.Error as e:
            logger.error("insert_reading failed for node '%s': %s", row["node_id"], e)
        finally:
            conn.close()


def insert_alert(data: dict):
    """
    Insert an alert record into the alerts table.

    Args:
        data (dict): Must contain 'node_id', 'type', 'message'.
                     'timestamp' defaults to now if not provided.
    """
    sql = """
    INSERT INTO alerts (node_id, location, timestamp, type, message)
    VALUES (:node_id, :location, :timestamp, :type, :message)
    """
    row = {
        "node_id":   data.get("node_id", "unknown"),
        "location":  data.get("location", ""),
        "timestamp": data.get("timestamp", datetime.now().isoformat()),
        "type":      data.get("type", "info"),
        "message":   data.get("message", ""),
    }

    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(sql, row)
            conn.commit()
        except sqlite3.Error as e:
            logger.error("insert_alert failed for node '%s': %s", row["node_id"], e)
        finally:
            conn.close()


def upsert_node_status(data: dict):
    """
    Insert or replace a node_status record (keyed by node_id).

    Args:
        data (dict): Must contain 'node_id'. Other fields are optional.
    """
    sql = """
    INSERT OR REPLACE INTO node_status
        (node_id, location, status, ip, rssi, uptime, relay, last_seen)
    VALUES
        (:node_id, :location, :status, :ip, :rssi, :uptime, :relay, :last_seen)
    """
    row = {
        "node_id":   data.get("node_id", "unknown"),
        "location":  data.get("location", ""),
        "status":    data.get("status", "online"),
        "ip":        data.get("ip", ""),
        "rssi":      data.get("rssi", 0),
        "uptime":    data.get("uptime", 0),
        "relay":     int(data.get("relay", 0)),
        "last_seen": data.get("last_seen", datetime.now().isoformat()),
    }

    with _db_lock:
        conn = _get_connection()
        try:
            conn.execute(sql, row)
            conn.commit()
        except sqlite3.Error as e:
            logger.error("upsert_node_status failed for node '%s': %s", row["node_id"], e)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# QUERY operations
# ---------------------------------------------------------------------------

def get_latest_readings(node_id: Optional[str] = None) -> list:
    """
    Return the most recent reading for each node (or for a specific node).

    Args:
        node_id (str, optional): If provided, filter to that node only.

    Returns:
        list[dict]: One dict per node with the latest sensor values.
    """
    if node_id:
        sql = """
        SELECT * FROM readings
        WHERE node_id = ?
        ORDER BY timestamp DESC
        LIMIT 1
        """
        params = (node_id,)
    else:
        sql = """
        SELECT r.* FROM readings r
        INNER JOIN (
            SELECT node_id, MAX(timestamp) AS max_ts
            FROM readings
            GROUP BY node_id
        ) latest ON r.node_id = latest.node_id AND r.timestamp = latest.max_ts
        ORDER BY r.node_id
        """
        params = ()

    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.execute(sql, params)
            rows = [_row_to_dict(r) for r in cursor.fetchall()]
            return rows
        except sqlite3.Error as e:
            logger.error("get_latest_readings failed: %s", e)
            return []
        finally:
            conn.close()


def get_history(node_id: str, hours: int = 24) -> list:
    """
    Retrieve all readings for a node within the last N hours.

    Args:
        node_id (str): The node to query.
        hours   (int): How many hours back to look (default 24).

    Returns:
        list[dict]: Readings in ascending timestamp order.
    """
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    sql = """
    SELECT * FROM readings
    WHERE node_id = ? AND timestamp >= ?
    ORDER BY timestamp ASC
    """

    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.execute(sql, (node_id, cutoff))
            return [_row_to_dict(r) for r in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("get_history failed for node '%s': %s", node_id, e)
            return []
        finally:
            conn.close()


def get_daily_summary() -> list:
    """
    Return total energy consumed per node for today (midnight to now).

    Returns:
        list[dict]: Each dict has 'node_id', 'location', 'total_kwh'.
    """
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    sql = """
    SELECT
        node_id,
        MAX(location)   AS location,
        MAX(energy_kwh) - MIN(energy_kwh) AS total_kwh
    FROM readings
    WHERE timestamp >= ?
    GROUP BY node_id
    ORDER BY node_id
    """

    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.execute(sql, (today_start,))
            return [_row_to_dict(r) for r in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("get_daily_summary failed: %s", e)
            return []
        finally:
            conn.close()


def get_alerts(limit: int = 50) -> list:
    """
    Retrieve the most recent alerts.

    Args:
        limit (int): Maximum number of alerts to return (default 50).

    Returns:
        list[dict]: Alerts in descending timestamp order (newest first).
    """
    sql = """
    SELECT * FROM alerts
    ORDER BY timestamp DESC
    LIMIT ?
    """

    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.execute(sql, (limit,))
            return [_row_to_dict(r) for r in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("get_alerts failed: %s", e)
            return []
        finally:
            conn.close()


def get_all_node_statuses() -> list:
    """
    Return status information for all known nodes.

    Returns:
        list[dict]: One dict per node with connection and relay state.
    """
    sql = "SELECT * FROM node_status ORDER BY node_id"

    with _db_lock:
        conn = _get_connection()
        try:
            cursor = conn.execute(sql)
            return [_row_to_dict(r) for r in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error("get_all_node_statuses failed: %s", e)
            return []
        finally:
            conn.close()
