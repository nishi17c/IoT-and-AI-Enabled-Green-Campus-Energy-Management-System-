# ⚡ IoT & AI Enabled Green Campus Energy Management System

> **B.Tech Final Year Project** — Real-time IoT energy monitoring with AI-powered demand forecasting, fault detection, and automated optimization.

## 🔗 Live Dashboard
**[👉 Open Dashboard](https://nishi17c.github.io/IoT-and-AI-Enabled-Green-Campus-Energy-Management-System/)**

---

## 📌 Project Overview
An IoT and AI-enabled system to continuously monitor energy usage across an educational campus, provide intelligent insights, automate energy optimization, and support a sustainable, energy-efficient campus.

## 🔧 Tech Stack
| Layer | Technology |
|---|---|
| Hardware | NodeMCU ESP8266, PZEM-004T, DHT11, PIR, LDR, Relay |
| Communication | MQTT (Mosquitto), WiFi |
| Backend | Python FastAPI, SQLite |
| AI/ML | LSTM (TensorFlow), Isolation Forest (scikit-learn) |
| Dashboard | HTML5, CSS3, Chart.js |
| Hosting | GitHub Pages |

## 📊 Dashboard Features
- **Live Monitoring** — Voltage, Current, Power, Energy, Temperature, CO₂
- **AI Forecast** — LSTM 24-hour energy demand prediction
- **Fault Detection** — Isolation Forest anomaly detection
- **Remote Control** — Relay ON/OFF from browser
- **History** — Daily / Weekly / Monthly consumption charts
- **Alerts** — Real-time fault & anomaly notifications
- **Leaderboard** — Department-wise energy efficiency ranking

## 🏗️ System Architecture
```
[IoT Sensor Node (ESP8266 + PZEM-004T)]
         ↓ MQTT over WiFi
[Edge Server (Laptop / RPi)]
         ↓ REST API
[AI/ML Engine (Python)]
         ↓
[Web Dashboard (This Page)]
```

## 👨‍💻 Team
B.Tech Final Year | 2025–2026

---
*🌿 Building a greener campus, one kWh at a time.*
