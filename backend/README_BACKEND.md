# 🌿 Green Campus EMS — Backend

> **IoT & AI Enabled Green Campus Energy Management System**  
> Python FastAPI backend for ESP8266 NodeMCU sensor nodes.

---

## 📋 Prerequisites

| Requirement | Version | Download |
|---|---|---|
| Python | 3.8 or higher | https://www.python.org/downloads/ |
| Mosquitto MQTT Broker | 2.x | https://mosquitto.org/download/ |
| pip | latest | bundled with Python |

> **Windows quick install via winget:**
> ```
> winget install EclipseFoundation.Mosquitto
> winget install Python.Python.3.11
> ```

---

## 🦟 Installing & Configuring Mosquitto on Windows

### 1. Install Mosquitto
Download the Windows installer from https://mosquitto.org/download/ and run it.  
Default install path: `C:\Program Files\mosquitto\`

### 2. Allow Anonymous Connections (Development)
Edit (or create) `C:\Program Files\mosquitto\mosquitto.conf`:

```conf
# mosquitto.conf — development settings
listener 1883
allow_anonymous true
```

> **⚠️ Production:** Use password files and TLS. See the Mosquitto docs.

### 3. Start Mosquitto as a Windows Service
```powershell
# Run PowerShell as Administrator
net start mosquitto

# Verify it's running
sc query mosquitto
```

Or start manually:
```cmd
"C:\Program Files\mosquitto\mosquitto.exe" -v -c "C:\Program Files\mosquitto\mosquitto.conf"
```

---

## 🚀 Running the Backend

### Option A — Double-click (easiest)
Just double-click **`start.bat`** in this folder.  
It will:
1. Check if Mosquitto is running and start it if not
2. Run `pip install -r requirements.txt`
3. Launch the FastAPI server

### Option B — Manual (PowerShell / CMD)
```powershell
cd C:\Users\Nishikant\Desktop\Mproject\backend

# Install dependencies
pip install -r requirements.txt

# Start the server
python server.py
```

The server starts on **http://localhost:8000**.

---

## 🔗 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serves the dashboard `index.html` |
| `GET` | `/api/nodes` | All nodes with latest readings + status |
| `GET` | `/api/nodes/{node_id}/live` | Live reading for one node |
| `GET` | `/api/nodes/{node_id}/history?hours=24` | Historical readings (1–168 h) |
| `GET` | `/api/analytics/daily` | Daily kWh, cost (₹), CO₂ per node |
| `GET` | `/api/alerts?limit=20` | Recent alerts |
| `POST` | `/api/control/relay` | Send relay on/off/toggle command |
| `GET` | `/api/health` | Health check |
| `WS` | `/ws` | WebSocket real-time stream |
| `GET` | `/docs` | Swagger UI (interactive API docs) |

### Relay Control — Example
```bash
curl -X POST http://localhost:8000/api/control/relay \
     -H "Content-Type: application/json" \
     -d '{"node_id": "node-01", "command": "off"}'
```

---

## 📡 MQTT Topics (ESP8266 → Server)

| Topic | Payload | Description |
|-------|---------|-------------|
| `campus/{node_id}/energy` | JSON | PZEM-004T power readings |
| `campus/{node_id}/environment` | JSON | DHT22 + PIR + LDR data |
| `campus/{node_id}/status` | JSON | Node heartbeat / connection info |
| `campus/{node_id}/alert` | JSON | Node-generated alerts |
| `campus/{node_id}/relay` | JSON | **Server → Node** relay command |

### Example Energy Payload
```json
{
  "node_id": "node-01",
  "location": "Lab Block A",
  "voltage": 231.5,
  "current": 2.34,
  "power_kw": 0.541,
  "energy_kwh": 12.34,
  "session_kwh": 0.12,
  "frequency": 50.0,
  "power_factor": 0.97,
  "relay_state": 1,
  "timestamp": "2024-01-15T14:23:05"
}
```

### Example Environment Payload
```json
{
  "node_id": "node-01",
  "temperature": 28.5,
  "humidity": 62.0,
  "motion": 1,
  "light_pct": 43.2
}
```

---

## 🖥️ Connecting the Dashboard (index.html)

Your `index.html` frontend should connect to the WebSocket to receive live updates:

```javascript
// In your dashboard JavaScript — replace the simulation with real data
const ws = new WebSocket("ws://localhost:8000/ws");

ws.onopen = () => {
    console.log("Connected to EMS WebSocket");
};

ws.onmessage = (event) => {
    const packet = JSON.parse(event.data);
    // packet.nodes is an array of node objects
    packet.nodes.forEach(node => {
        updateNodeCard(node);        // update your UI card
        updateChart(node);           // push to your Chart.js charts
    });
};

ws.onclose = () => {
    console.warn("WebSocket disconnected — attempting reconnect…");
    setTimeout(() => location.reload(), 3000);
};
```

For the REST API, use `fetch`:

```javascript
// Get daily analytics
fetch("http://localhost:8000/api/analytics/daily")
    .then(r => r.json())
    .then(data => {
        document.getElementById("total-kwh").textContent =
            data.campus_total.total_kwh.toFixed(2);
        document.getElementById("total-cost").textContent =
            "₹" + data.campus_total.cost_inr.toFixed(2);
        document.getElementById("total-co2").textContent =
            data.campus_total.co2_kg.toFixed(2) + " kg";
    });
```

---

## 🗄️ Database

The backend creates **`campus_ems.db`** (SQLite) in the `backend/` folder automatically on first run.  
You can inspect it with [DB Browser for SQLite](https://sqlitebrowser.org/) — free GUI tool.

Tables:
- **readings** — all sensor readings (timestamped)
- **alerts** — threshold violations and node-generated alerts
- **node_status** — latest heartbeat info per node

---

## 🔧 Troubleshooting

### MQTT not connecting
- Make sure Mosquitto is running: `sc query mosquitto`
- Check the broker is listening: `netstat -an | findstr 1883`
- Ensure `allow_anonymous true` is in `mosquitto.conf`
- Check Windows Firewall is not blocking port 1883

### PZEM returning NaN / 0 values
- Verify the ESP8266 UART pins are correctly wired (TX→RX, RX→TX)
- PZEM-004T needs mains voltage on its power terminals to respond
- Check the `Serial2.begin(9600)` baud rate matches the PZEM firmware version
- NaN values are filtered out by the backend (default to 0.0) so they won't crash the server

### Port 8000 already in use
```powershell
# Find what's using port 8000
netstat -ano | findstr :8000

# Kill it (replace PID with the actual PID number)
taskkill /PID <PID> /F
```

### ModuleNotFoundError
```powershell
# Re-run pip install
pip install -r requirements.txt --force-reinstall
```

### Python not found in PATH
- Reinstall Python and tick **"Add Python to PATH"** during setup
- Or add manually: `C:\Users\<you>\AppData\Local\Programs\Python\Python311\` to PATH

### WebSocket connection refused in browser
- Make sure the server is running (`python server.py`)
- Check browser console for CORS errors
- Try `ws://127.0.0.1:8000/ws` instead of `localhost`

---

## 📁 File Structure

```
backend/
├── database.py        # SQLite database layer (thread-safe)
├── mqtt_client.py     # MQTT subscriber + publisher
├── alerts.py          # Threshold checking + alert formatting
├── server.py          # FastAPI main application
├── requirements.txt   # Python dependencies
├── start.bat          # Windows one-click launcher
└── README_BACKEND.md  # This file
```

---

## 🙏 Credits

Built for the **IoT & AI Enabled Green Campus Energy Management System** project.  
Hardware: ESP8266 NodeMCU + PZEM-004T + DHT22 + PIR sensor + LDR.  
Software stack: Python 3.11 · FastAPI · paho-mqtt · SQLite · Mosquitto.
