"""
server.py — FastAPI Main Server
================================
IoT Green Campus Energy Management System

Provides:
  - WebSocket endpoint for real-time dashboard updates (/ws)
  - REST API for nodes, history, analytics, alerts, and relay control
  - Static file serving for the frontend dashboard
  - CORS enabled for all origins (development mode)

Usage:
  python server.py

Access points:
  Dashboard : http://localhost:8000
  API Docs  : http://localhost:8000/docs  (Swagger UI)
  WebSocket : ws://localhost:8000/ws
"""

# ============================================================
# STARTUP BANNER — printed before any imports so it's visible
# even if an import fails.
# ============================================================
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
print("\n" + "=" * 60)
print("  Green Campus Energy Management System")
print("=" * 60)
print("  Dashboard  : http://localhost:8000")
print("  API Docs   : http://localhost:8000/docs")
print("  WebSocket  : ws://localhost:8000/ws")
print("=" * 60 + "\n")

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database
import mqtt_client

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Green Campus EMS API",
    description=(
        "REST & WebSocket API for the IoT-enabled Green Campus "
        "Energy Management System. Powered by ESP8266 NodeMCU + PZEM-004T."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Allow all origins during development.
# In production replace ["*"] with your actual frontend domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class _ConnectionManager:
    """Manages a set of active WebSocket connections."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        logger.info("WebSocket client connected. Total: %d", len(self.active))

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
        logger.info("WebSocket client disconnected. Total: %d", len(self.active))

    async def broadcast(self, data: dict):
        """Send JSON data to all connected WebSocket clients."""
        if not self.active:
            return
        payload = json.dumps(data, default=str)
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = _ConnectionManager()


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event():
    """Initialise the database and start the MQTT background thread."""
    logger.info("Starting up Green Campus EMS server…")
    database.init_db()
    mqtt_client.start_mqtt_thread()

    # Launch the WebSocket broadcaster as a background task
    asyncio.create_task(_ws_broadcaster())
    logger.info("Server ready.")


# ---------------------------------------------------------------------------
# Background WebSocket broadcaster
# ---------------------------------------------------------------------------

async def _ws_broadcaster():
    """
    Background coroutine: every 2 seconds, assemble a full snapshot of
    all node data and push it to every connected WebSocket client.
    """
    while True:
        await asyncio.sleep(2)
        try:
            if manager.active:
                snapshot = _build_snapshot()
                await manager.broadcast(snapshot)
        except Exception as e:
            logger.error("WebSocket broadcaster error: %s", e)


def _build_snapshot() -> dict:
    """
    Combine MQTT in-memory live data with DB node statuses into a single
    dict that the dashboard can render immediately.
    """
    live      = mqtt_client.get_latest_data()          # {node_id: reading_dict}
    statuses  = database.get_all_node_statuses()        # list of status dicts
    status_map = {s["node_id"]: s for s in statuses}

    nodes = []
    all_ids = set(live.keys()) | set(status_map.keys())
    for nid in sorted(all_ids):
        entry = {}
        entry.update(status_map.get(nid, {}))  # DB status fields first
        entry.update(live.get(nid, {}))         # Override/add with live data
        entry["node_id"] = nid
        nodes.append(entry)

    return {
        "type":      "update",
        "timestamp": datetime.now().isoformat(),
        "nodes":     nodes,
    }


# ---------------------------------------------------------------------------
# WebSocket Endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Real-time data stream endpoint.
    Each connected client receives a JSON snapshot every 2 seconds
    (pushed by _ws_broadcaster). The client can also send messages,
    though the server doesn't currently act on them.
    """
    await manager.connect(websocket)
    try:
        # Send an immediate first packet so the dashboard doesn't wait 2 s
        await websocket.send_text(json.dumps(_build_snapshot(), default=str))
        # Keep the connection alive by listening (handles ping/pong too)
        while True:
            await websocket.receive_text()   # blocks until client sends or disconnects
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# REST Endpoints — Nodes
# ---------------------------------------------------------------------------

@app.get("/api/nodes", summary="All nodes with latest readings and status")
async def get_all_nodes():
    """
    Return the latest sensor reading + connection status for every node.
    Combines the MQTT in-memory cache with the node_status table.
    """
    return JSONResponse(content=_build_snapshot())


@app.get("/api/nodes/{node_id}/live", summary="Latest reading for a specific node")
async def get_node_live(node_id: str):
    """
    Return the most recent combined reading for a single node.
    If the node has no data yet, returns a 404.
    """
    live = mqtt_client.get_latest_data()
    db_readings = database.get_latest_readings(node_id=node_id)

    result = {}
    if db_readings:
        result.update(db_readings[0])
    if node_id in live:
        result.update(live[node_id])

    if not result:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found or has no data yet.")

    result["node_id"] = node_id
    return JSONResponse(content=result)


@app.get("/api/nodes/{node_id}/history", summary="Historical readings for a node")
async def get_node_history(
    node_id: str,
    hours: int = Query(default=24, ge=1, le=168, description="Hours of history to retrieve (1–168)"),
):
    """
    Return all stored readings for a node within the last N hours.
    Useful for time-series charts on the dashboard.
    """
    history = database.get_history(node_id=node_id, hours=hours)
    return JSONResponse(content={
        "node_id": node_id,
        "hours":   hours,
        "count":   len(history),
        "data":    history,
    })


# ---------------------------------------------------------------------------
# REST Endpoints — Analytics
# ---------------------------------------------------------------------------

COST_PER_KWH = 5.0    # ₹ per kWh (Indian electricity tariff)
CO2_PER_KWH  = 0.82   # kg CO₂ per kWh (India grid emission factor)


@app.get("/api/analytics/daily", summary="Daily kWh summary, cost, and CO₂ per node")
async def get_daily_analytics():
    """
    Aggregate today's energy consumption per node and compute:
      - Total kWh consumed
      - Estimated cost at ₹5/kWh
      - CO₂ equivalent emissions (0.82 kg per kWh)

    Returns a per-node breakdown plus a campus-wide total.
    """
    summary = database.get_daily_summary()

    nodes_out = []
    campus_kwh  = 0.0
    campus_cost = 0.0
    campus_co2  = 0.0

    for row in summary:
        kwh  = max(row.get("total_kwh") or 0.0, 0.0)   # guard against None / negative
        cost = round(kwh * COST_PER_KWH, 2)
        co2  = round(kwh * CO2_PER_KWH, 3)

        campus_kwh  += kwh
        campus_cost += cost
        campus_co2  += co2

        nodes_out.append({
            "node_id":   row["node_id"],
            "location":  row.get("location", ""),
            "total_kwh": round(kwh, 4),
            "cost_inr":  cost,
            "co2_kg":    co2,
        })

    return JSONResponse(content={
        "date":         datetime.now().strftime("%Y-%m-%d"),
        "nodes":        nodes_out,
        "campus_total": {
            "total_kwh":  round(campus_kwh, 4),
            "cost_inr":   round(campus_cost, 2),
            "co2_kg":     round(campus_co2, 3),
        },
    })


# ---------------------------------------------------------------------------
# REST Endpoints — Alerts
# ---------------------------------------------------------------------------

@app.get("/api/alerts", summary="Recent system alerts")
async def get_alerts(
    limit: int = Query(default=20, ge=1, le=200, description="Number of recent alerts to return"),
):
    """
    Return the most recent alert records from the database.
    Alerts are ordered newest-first.
    """
    alerts = database.get_alerts(limit=limit)
    return JSONResponse(content={
        "count":  len(alerts),
        "alerts": alerts,
    })


# ---------------------------------------------------------------------------
# REST Endpoints — Relay Control
# ---------------------------------------------------------------------------

class RelayCommand(BaseModel):
    """Request body for the relay control endpoint."""
    node_id: str
    command: str   # 'on' | 'off' | 'toggle'


@app.post("/api/control/relay", summary="Send relay on/off/toggle command to a node")
async def control_relay(cmd: RelayCommand):
    """
    Publish an MQTT relay control command to campus/{node_id}/relay.
    The ESP8266 subscribes to this topic and actuates the relay.

    Body:
        node_id (str): Target node ID.
        command (str): 'on', 'off', or 'toggle'.
    """
    allowed = {"on", "off", "toggle"}
    if cmd.command.lower() not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid command '{cmd.command}'. Must be one of: {allowed}",
        )

    mqtt_client.publish_relay_command(cmd.node_id, cmd.command.lower())

    logger.info("Relay command '%s' dispatched to node '%s'", cmd.command, cmd.node_id)
    return JSONResponse(content={
        "status":  "sent",
        "node_id": cmd.node_id,
        "command": cmd.command.lower(),
        "ts":      datetime.now().isoformat(),
    })


# ---------------------------------------------------------------------------
# REST Endpoints — Health
# ---------------------------------------------------------------------------

@app.get("/api/health", summary="Server health check")
async def health_check():
    """
    Simple health endpoint.  Returns connected node count and server time.
    Useful for monitoring and load balancer probes.
    """
    live = mqtt_client.get_latest_data()
    return JSONResponse(content={
        "status":          "ok",
        "timestamp":       datetime.now().isoformat(),
        "connected_nodes": len(live),
    })


# ---------------------------------------------------------------------------
# Static — serve the frontend dashboard
# ---------------------------------------------------------------------------

# Resolve path to the index.html one level above backend/
_FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_INDEX_HTML   = os.path.join(_FRONTEND_DIR, "index.html")


@app.get("/", include_in_schema=False)
async def serve_dashboard():
    """
    Serve the frontend dashboard HTML file.
    The file is expected at ../index.html (relative to backend/).
    """
    if os.path.isfile(_INDEX_HTML):
        return FileResponse(_INDEX_HTML, media_type="text/html")
    # Fallback: friendly error if dashboard not found
    return JSONResponse(
        status_code=404,
        content={
            "error": "Dashboard not found.",
            "hint":  f"Place your index.html at: {_INDEX_HTML}",
            "api":   "http://localhost:8000/docs",
        },
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False,       # Set True for development hot-reload
        log_level="info",
    )
