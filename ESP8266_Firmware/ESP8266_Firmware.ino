/*
 * ============================================================
 *   IoT & AI Enabled Green Campus Energy Management System
 *   ESP8266 (NodeMCU) Sensor Node Firmware
 * ============================================================
 *   Sensors  : PZEM-004T v3 | DHT11 | PIR HC-SR501 | LDR
 *   Display  : OLED 0.96" I2C (SSD1306)
 *   Control  : 5V Relay Module
 *   Protocol : MQTT over WiFi → Python Backend
 * ============================================================
 *   REQUIRED LIBRARIES (install via Arduino Library Manager):
 *   - PubSubClient          by Nick O'Leary
 *   - PZEM004Tv30           by Olexa Prokopenko
 *   - DHT sensor library    by Adafruit
 *   - Adafruit GFX Library  by Adafruit
 *   - Adafruit SSD1306      by Adafruit
 *   - ArduinoJson           by Benoit Blanchon
 *
 *   BOARD: NodeMCU 1.0 (ESP-12E Module)
 *   Install ESP8266 board: https://arduino.esp8266.com/stable/package_esp8266com_index.json
 * ============================================================
 *
 *   PIN CONNECTIONS:
 *   ┌─────────────────┬──────────┬───────────────────────────┐
 *   │ Component       │ NodeMCU  │ Notes                     │
 *   ├─────────────────┼──────────┼───────────────────────────┤
 *   │ PZEM-004T TX    │ D6 (RX)  │ SoftwareSerial            │
 *   │ PZEM-004T RX    │ D5 (TX)  │ SoftwareSerial            │
 *   │ PZEM-004T GND   │ GND      │                           │
 *   │ PZEM-004T 5V    │ VIN/5V   │ Use external 5V if needed │
 *   ├─────────────────┼──────────┼───────────────────────────┤
 *   │ DHT11 DATA      │ D3       │ With 10kΩ pull-up to 3.3V │
 *   │ DHT11 VCC       │ 3.3V     │                           │
 *   │ DHT11 GND       │ GND      │                           │
 *   ├─────────────────┼──────────┼───────────────────────────┤
 *   │ PIR OUT         │ D7       │                           │
 *   │ PIR VCC         │ VIN/5V   │ PIR needs 5V              │
 *   │ PIR GND         │ GND      │                           │
 *   ├─────────────────┼──────────┼───────────────────────────┤
 *   │ LDR + 10kΩ      │ A0       │ Voltage divider to GND    │
 *   ├─────────────────┼──────────┼───────────────────────────┤
 *   │ OLED SDA        │ D2       │ I2C Data                  │
 *   │ OLED SCL        │ D1       │ I2C Clock                 │
 *   │ OLED VCC        │ 3.3V     │                           │
 *   │ OLED GND        │ GND      │                           │
 *   ├─────────────────┼──────────┼───────────────────────────┤
 *   │ RELAY IN        │ D0       │ LOW = ON, HIGH = OFF       │
 *   │ RELAY VCC       │ 5V       │                           │
 *   │ RELAY GND       │ GND      │                           │
 *   └─────────────────┴──────────┴───────────────────────────┘
 *
 *   ⚠️  SAFETY WARNING:
 *   NEVER connect ESP8266 directly to 230V mains.
 *   Use PZEM-004T's isolated CT clamp for AC measurement.
 *   Always test with a low-power load (lamp/phone charger) first.
 * ============================================================
 */

// ── INCLUDES ──────────────────────────────────────────────────
#include <ESP8266WiFi.h>          // WiFi library for ESP8266
#include <PubSubClient.h>         // MQTT client
#include <SoftwareSerial.h>       // Software UART for PZEM-004T
#include <PZEM004Tv30.h>          // PZEM-004T v3.0 energy meter
#include <DHT.h>                  // DHT11 temperature & humidity
#include <Wire.h>                 // I2C for OLED
#include <Adafruit_GFX.h>         // OLED graphics base
#include <Adafruit_SSD1306.h>     // OLED SSD1306 driver
#include <ArduinoJson.h>          // JSON for MQTT payloads


// ═══════════════════════════════════════════════════════════════
//   ⚙️  CONFIGURATION — EDIT THESE VALUES FOR YOUR SETUP
// ═══════════════════════════════════════════════════════════════

// ── WiFi Credentials ──────────────────────────────────────────
const char* WIFI_SSID     = "OPPO F29 5G j7j4";     // <-- Change this
const char* WIFI_PASSWORD = "12345678"; // <-- Change this

// ── MQTT Broker ───────────────────────────────────────────────
// Run Mosquitto on your laptop. Find laptop IP: run "ipconfig" in CMD
// Look for IPv4 Address under WiFi adapter (e.g. 192.168.1.5)
const char* MQTT_SERVER   = "10.29.221.43";  // <-- Your laptop's IP
const int   MQTT_PORT     = 1883;
const char* MQTT_USER     = "";             // Leave blank if no auth
const char* MQTT_PASSWORD = "";             // Leave blank if no auth

// ── Node Identity ─────────────────────────────────────────────
// Change NODE_ID for each sensor node (node1, node2, node3...)
const char* NODE_ID       = "node1";
const char* NODE_LOCATION = "Lab A";

// ── MQTT Topics ───────────────────────────────────────────────
// Data published by this node:
String TOPIC_ENERGY  = String("campus/") + NODE_ID + "/energy";
String TOPIC_ENV     = String("campus/") + NODE_ID + "/environment";
String TOPIC_STATUS  = String("campus/") + NODE_ID + "/status";
String TOPIC_ALERT   = String("campus/") + NODE_ID + "/alert";
// Commands received by this node:
String TOPIC_RELAY   = String("campus/") + NODE_ID + "/relay";

// ── Thresholds for Auto-Alerts ────────────────────────────────
const float VOLTAGE_HIGH  = 250.0;  // Volts — over-voltage alert
const float VOLTAGE_LOW   = 200.0;  // Volts — under-voltage alert
const float CURRENT_HIGH  = 10.0;   // Amps  — overcurrent alert
const float PF_LOW        = 0.80;   // Power factor — poor PF alert
const float TEMP_HIGH     = 40.0;   // °C    — high temperature alert

// ── Timing Configuration ─────────────────────────────────────
const unsigned long SENSOR_INTERVAL    = 5000;  // Read sensors every 5s
const unsigned long OLED_ROTATE_MS     = 3000;  // Rotate OLED screen every 3s
const unsigned long HEARTBEAT_INTERVAL = 60000; // Heartbeat every 60s


// ═══════════════════════════════════════════════════════════════
//   📌 PIN DEFINITIONS
// ═══════════════════════════════════════════════════════════════
#define PIN_PZEM_RX   D6   // GPIO12 — SoftSerial RX (connects to PZEM TX)
#define PIN_PZEM_TX   D5   // GPIO14 — SoftSerial TX (connects to PZEM RX)
#define PIN_DHT       D3   // GPIO0  — DHT11 data pin
#define PIN_PIR       D7   // GPIO13 — PIR motion sensor output
#define PIN_LDR       A0   // Analog — LDR light sensor
#define PIN_RELAY     D0   // GPIO16 — Relay control (LOW = ON)

#define DHT_TYPE      DHT11

// ── OLED Display ──────────────────────────────────────────────
#define OLED_WIDTH    128
#define OLED_HEIGHT   64
#define OLED_RESET    -1   // Reset pin (-1 = share Arduino reset)
#define OLED_ADDRESS  0x3C // I2C address (try 0x3D if display blank)


// ═══════════════════════════════════════════════════════════════
//   🔧 OBJECT DECLARATIONS
// ═══════════════════════════════════════════════════════════════
SoftwareSerial         pzemSerial(PIN_PZEM_RX, PIN_PZEM_TX);
PZEM004Tv30            pzem(pzemSerial);
DHT                    dht(PIN_DHT, DHT_TYPE);
Adafruit_SSD1306       display(OLED_WIDTH, OLED_HEIGHT, &Wire, OLED_RESET);
WiFiClient             wifiClient;
PubSubClient           mqttClient(wifiClient);


// ═══════════════════════════════════════════════════════════════
//   📊 SENSOR DATA VARIABLES
// ═══════════════════════════════════════════════════════════════
// PZEM-004T readings
float voltage     = 0.0;
float current     = 0.0;
float power       = 0.0;
float energy      = 0.0;   // kWh accumulated
float frequency   = 0.0;
float powerFactor = 0.0;

// DHT11 readings
float temperature = 0.0;
float humidity    = 0.0;

// Other sensors
bool  motionDetected = false;
int   ldrRaw         = 0;    // 0–1023 raw ADC value
int   lightPercent   = 0;    // 0–100% light level

// State
bool  relayState     = false; // false = OFF, true = ON
int   oledScreen     = 0;     // Current OLED screen (0,1,2,3)
bool  pzemOk         = false; // PZEM sensor valid?

// Timers
unsigned long lastSensorRead    = 0;
unsigned long lastOledRotate    = 0;
unsigned long lastHeartbeat     = 0;
unsigned long lastReconnectAttempt = 0;

// Energy session tracking
float sessionEnergy = 0.0;  // kWh since node boot


// ═══════════════════════════════════════════════════════════════
//   🔄 MQTT CALLBACK — Runs when a subscribed message arrives
// ═══════════════════════════════════════════════════════════════
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  // Convert payload bytes to string
  String message = "";
  for (unsigned int i = 0; i < length; i++) {
    message += (char)payload[i];
  }
  message.toLowerCase();

  Serial.print("[MQTT] Received on ");
  Serial.print(topic);
  Serial.print(" → ");
  Serial.println(message);

  // ── Relay Control ──────────────────────────────────────────
  // Send "on" or "1" to turn relay ON
  // Send "off" or "0" to turn relay OFF
  // Send "toggle" to flip current state
  if (String(topic) == TOPIC_RELAY) {
    if (message == "on" || message == "1" || message == "true") {
      setRelay(true);
    } else if (message == "off" || message == "0" || message == "false") {
      setRelay(false);
    } else if (message == "toggle") {
      setRelay(!relayState);
    }
  }
}


// ═══════════════════════════════════════════════════════════════
//   ⚡ RELAY CONTROL
// ═══════════════════════════════════════════════════════════════
void setRelay(bool state) {
  relayState = state;
  // Most relay modules are ACTIVE LOW (LOW = relay energized = ON)
  digitalWrite(PIN_RELAY, state ? LOW : HIGH);

  Serial.print("[RELAY] → ");
  Serial.println(state ? "ON" : "OFF");

  // Publish confirmation back to dashboard
  String confirmTopic = String("campus/") + NODE_ID + "/relay/state";
  mqttClient.publish(confirmTopic.c_str(), state ? "on" : "off", true);
}


// ═══════════════════════════════════════════════════════════════
//   📡 WIFI CONNECTION
// ═══════════════════════════════════════════════════════════════
void connectWiFi() {
  Serial.print("\n[WiFi] Connecting to: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  // Show connecting animation on OLED
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(10, 20);
  display.println("Connecting WiFi...");
  display.setCursor(10, 35);
  display.println(WIFI_SSID);
  display.display();

  int attempt = 0;
  while (WiFi.status() != WL_CONNECTED && attempt < 30) {
    delay(500);
    Serial.print(".");
    attempt++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Connected!");
    Serial.print("[WiFi] IP Address: ");
    Serial.println(WiFi.localIP());

    display.clearDisplay();
    display.setCursor(0, 10);
    display.println("WiFi Connected!");
    display.setCursor(0, 25);
    display.println(WiFi.localIP().toString());
    display.display();
    delay(2000);
  } else {
    Serial.println("\n[WiFi] FAILED — running offline (data saved locally)");
    display.clearDisplay();
    display.setCursor(0, 20);
    display.println("WiFi FAILED");
    display.println("Offline mode");
    display.display();
    delay(2000);
  }
}


// ═══════════════════════════════════════════════════════════════
//   📮 MQTT CONNECTION
// ═══════════════════════════════════════════════════════════════
void connectMQTT() {
  if (WiFi.status() != WL_CONNECTED) return;

  Serial.print("[MQTT] Connecting to broker: ");
  Serial.println(MQTT_SERVER);

  // Client ID must be unique — use Node ID + chip ID
  String clientId = String("EMS-") + NODE_ID + "-" + String(ESP.getChipId(), HEX);

  // Last Will & Testament — broker publishes this if node disconnects
  String lwtTopic   = String("campus/") + NODE_ID + "/status";
  String lwtMessage = "{\"status\":\"offline\",\"node\":\"" + String(NODE_ID) + "\"}";

  bool connected = false;
  if (strlen(MQTT_USER) > 0) {
    connected = mqttClient.connect(
      clientId.c_str(),
      MQTT_USER, MQTT_PASSWORD,
      lwtTopic.c_str(), 0, true, lwtMessage.c_str()
    );
  } else {
    connected = mqttClient.connect(
      clientId.c_str(),
      lwtTopic.c_str(), 0, true, lwtMessage.c_str()
    );
  }

  if (connected) {
    Serial.println("[MQTT] Connected!");

    // Subscribe to relay control topic
    mqttClient.subscribe(TOPIC_RELAY.c_str());
    Serial.print("[MQTT] Subscribed to: ");
    Serial.println(TOPIC_RELAY);

    // Publish online status
    publishStatus("online");

  } else {
    Serial.print("[MQTT] Failed, rc=");
    Serial.println(mqttClient.state());
    /*
     * MQTT Error Codes:
     * -4 = MQTT_CONNECTION_TIMEOUT
     * -3 = MQTT_CONNECTION_LOST
     * -2 = MQTT_CONNECT_FAILED
     * -1 = MQTT_DISCONNECTED
     *  1 = MQTT_CONNECT_BAD_PROTOCOL
     *  2 = MQTT_CONNECT_BAD_CLIENT_ID
     *  3 = MQTT_CONNECT_UNAVAILABLE
     *  4 = MQTT_CONNECT_BAD_CREDENTIALS
     *  5 = MQTT_CONNECT_UNAUTHORIZED
     */
  }
}


// ═══════════════════════════════════════════════════════════════
//   📖 READ ALL SENSORS
// ═══════════════════════════════════════════════════════════════
void readSensors() {

  // ── 1. PZEM-004T v3 — Energy Meter ────────────────────────
  float v  = pzem.voltage();
  float i  = pzem.current();
  float p  = pzem.power();
  float e  = pzem.energy();
  float f  = pzem.frequency();
  float pf = pzem.pf();

  // isnan() checks if reading is valid (NaN = sensor error/not connected)
  if (!isnan(v) && !isnan(i) && !isnan(p)) {
    voltage     = v;
    current     = i;
    power       = p / 1000.0;  // Convert W → kW
    energy      = e;           // kWh (accumulated since PZEM reset)
    frequency   = f;
    powerFactor = pf;
    pzemOk      = true;

    // Track session energy (kWh since boot)
    // Approximation: power(kW) × (interval/3600s) = kWh increment
    sessionEnergy += power * (SENSOR_INTERVAL / 3600000.0);

    Serial.printf("[PZEM] V=%.1fV | I=%.2fA | P=%.3fkW | E=%.4fkWh | F=%.1fHz | PF=%.2f\n",
                  voltage, current, power, energy, frequency, powerFactor);
  } else {
    pzemOk = false;
    Serial.println("[PZEM] ⚠️  No data — check wiring! (SoftwareSerial pins D5/D6)");
    // Keep last valid reading, don't overwrite with NaN
  }

  // ── 2. DHT11 — Temperature & Humidity ─────────────────────
  float t = dht.readTemperature();
  float h = dht.readHumidity();

  if (!isnan(t) && !isnan(h)) {
    temperature = t;
    humidity    = h;
    Serial.printf("[DHT11] Temp=%.1f°C | Humidity=%.0f%%\n", temperature, humidity);
  } else {
    Serial.println("[DHT11] ⚠️  Read failed — check pin D3 and pull-up resistor");
  }

  // ── 3. PIR — Motion / Occupancy Detection ─────────────────
  motionDetected = digitalRead(PIN_PIR) == HIGH;
  Serial.printf("[PIR]   Motion = %s\n", motionDetected ? "YES" : "No");

  // ── 4. LDR — Light Intensity ───────────────────────────────
  ldrRaw       = analogRead(PIN_LDR);           // 0 (dark) to 1023 (bright)
  lightPercent = map(ldrRaw, 0, 1023, 100, 0);  // Invert: 0=dark → 100%dark
  // NOTE: LDR resistance increases in dark → voltage at A0 decreases
  // lightPercent here = darkness level (100% = very dark, 0% = very bright)
  // Rename to "darknessPercent" if you prefer
  Serial.printf("[LDR]   Raw=%d | Light=%d%%\n", ldrRaw, lightPercent);
}


// ═══════════════════════════════════════════════════════════════
//   🔔 PUBLISH STATUS (Online/Offline/Heartbeat)
// ═══════════════════════════════════════════════════════════════
void publishStatus(const char* statusStr) {
  StaticJsonDocument<256> doc;
  doc["node"]     = NODE_ID;
  doc["location"] = NODE_LOCATION;
  doc["status"]   = statusStr;
  doc["ip"]       = WiFi.localIP().toString();
  doc["rssi"]     = WiFi.RSSI();   // WiFi signal strength (dBm)
  doc["uptime"]   = millis() / 1000; // Seconds since boot
  doc["relay"]    = relayState ? "on" : "off";

  char jsonBuffer[256];
  serializeJson(doc, jsonBuffer);
  mqttClient.publish(TOPIC_STATUS.c_str(), jsonBuffer, true); // retain=true
  Serial.printf("[MQTT] Status published: %s\n", statusStr);
}


// ═══════════════════════════════════════════════════════════════
//   📤 PUBLISH ENERGY DATA
// ═══════════════════════════════════════════════════════════════
void publishEnergyData() {
  StaticJsonDocument<512> doc;

  // Node info
  doc["node"]      = NODE_ID;
  doc["location"]  = NODE_LOCATION;
  doc["timestamp"] = millis() / 1000;

  // PZEM-004T readings
  if (pzemOk) {
    doc["voltage"]      = serialized(String(voltage, 1));
    doc["current"]      = serialized(String(current, 2));
    doc["power_kw"]     = serialized(String(power, 3));
    doc["energy_kwh"]   = serialized(String(energy, 4));
    doc["session_kwh"]  = serialized(String(sessionEnergy, 4));
    doc["frequency"]    = serialized(String(frequency, 1));
    doc["power_factor"] = serialized(String(powerFactor, 2));
    doc["pzem_ok"]      = true;
  } else {
    doc["pzem_ok"] = false;
    doc["error"]   = "PZEM sensor not responding";
  }

  // System info
  doc["relay"] = relayState ? "on" : "off";
  doc["rssi"]  = WiFi.RSSI();

  char jsonBuffer[512];
  serializeJson(doc, jsonBuffer);

  bool ok = mqttClient.publish(TOPIC_ENERGY.c_str(), jsonBuffer);
  Serial.printf("[MQTT] Energy data %s → %s\n", ok ? "sent" : "FAILED", TOPIC_ENERGY.c_str());
  Serial.println(jsonBuffer);
}


// ═══════════════════════════════════════════════════════════════
//   📤 PUBLISH ENVIRONMENT DATA
// ═══════════════════════════════════════════════════════════════
void publishEnvData() {
  StaticJsonDocument<256> doc;

  doc["node"]        = NODE_ID;
  doc["location"]    = NODE_LOCATION;
  doc["temperature"] = serialized(String(temperature, 1));
  doc["humidity"]    = serialized(String(humidity, 0));
  doc["motion"]      = motionDetected ? 1 : 0;
  doc["light_raw"]   = ldrRaw;
  doc["light_pct"]   = lightPercent;
  doc["occupied"]    = motionDetected ? true : false;

  char jsonBuffer[256];
  serializeJson(doc, jsonBuffer);

  bool ok = mqttClient.publish(TOPIC_ENV.c_str(), jsonBuffer);
  Serial.printf("[MQTT] Env data %s → %s\n", ok ? "sent" : "FAILED", TOPIC_ENV.c_str());
}


// ═══════════════════════════════════════════════════════════════
//   🚨 PUBLISH ALERT (threshold violations)
// ═══════════════════════════════════════════════════════════════
void checkAndPublishAlerts() {
  String alertMsg = "";
  String alertType = "warn";

  if (pzemOk) {
    if (voltage > VOLTAGE_HIGH) {
      alertMsg = "HIGH VOLTAGE: " + String(voltage, 1) + "V";
      alertType = "error";
    } else if (voltage < VOLTAGE_LOW && voltage > 0) {
      alertMsg = "LOW VOLTAGE: " + String(voltage, 1) + "V";
      alertType = "warn";
    } else if (current > CURRENT_HIGH) {
      alertMsg = "OVERCURRENT: " + String(current, 2) + "A";
      alertType = "error";
    } else if (powerFactor < PF_LOW && powerFactor > 0) {
      alertMsg = "LOW POWER FACTOR: " + String(powerFactor, 2);
      alertType = "warn";
    }
  }

  if (temperature > TEMP_HIGH) {
    alertMsg = "HIGH TEMP: " + String(temperature, 1) + "°C";
    alertType = "warn";
  }

  // Motion after hours check (example: alert if motion after 22:00)
  // Add RTC module for real time — for now this is a placeholder
  // if (motionDetected && afterHours) { alertMsg = "Motion after hours"; }

  if (alertMsg.length() > 0) {
    StaticJsonDocument<256> doc;
    doc["node"]     = NODE_ID;
    doc["location"] = NODE_LOCATION;
    doc["type"]     = alertType;
    doc["message"]  = alertMsg;
    doc["value"]    = alertMsg; // dashboard uses this field

    char jsonBuffer[256];
    serializeJson(doc, jsonBuffer);

    mqttClient.publish(TOPIC_ALERT.c_str(), jsonBuffer);
    Serial.printf("[ALERT] 🚨 %s\n", alertMsg.c_str());
  }
}


// ═══════════════════════════════════════════════════════════════
//   📺 OLED DISPLAY — Rotates through 4 screens
// ═══════════════════════════════════════════════════════════════
void updateOLED() {
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  switch (oledScreen) {

    // ── Screen 0: Header + Power ─────────────────────────────
    case 0:
      display.setTextSize(1);
      display.setCursor(0, 0);
      display.print("GreenCampus EMS");
      display.setCursor(0, 10);
      display.print("Node: "); display.println(NODE_LOCATION);

      display.drawLine(0, 19, 127, 19, SSD1306_WHITE);

      display.setTextSize(2);
      display.setCursor(0, 24);
      if (pzemOk) {
        display.print(power, 2); display.print(" kW");
      } else {
        display.print("No Sensor");
      }

      display.setTextSize(1);
      display.setCursor(0, 54);
      display.print(WiFi.status() == WL_CONNECTED ? "WiFi:OK" : "WiFi:OFF");
      display.print(" MQTT:");
      display.print(mqttClient.connected() ? "OK" : "OFF");
      break;

    // ── Screen 1: Voltage & Current ──────────────────────────
    case 1:
      display.setTextSize(1);
      display.setCursor(0, 0);  display.print("── POWER QUALITY ──");

      display.setCursor(0, 14);
      display.print("Voltage  : ");
      display.print(pzemOk ? String(voltage, 1) + " V" : "---");

      display.setCursor(0, 26);
      display.print("Current  : ");
      display.print(pzemOk ? String(current, 2) + " A" : "---");

      display.setCursor(0, 38);
      display.print("Freq     : ");
      display.print(pzemOk ? String(frequency, 1) + " Hz" : "---");

      display.setCursor(0, 50);
      display.print("Pow.Fac  : ");
      display.print(pzemOk ? String(powerFactor, 2) : "---");
      break;

    // ── Screen 2: Energy & Environment ───────────────────────
    case 2:
      display.setTextSize(1);
      display.setCursor(0, 0);  display.print("── ENERGY & ENV ───");

      display.setCursor(0, 14);
      display.print("Energy   : ");
      display.print(pzemOk ? String(sessionEnergy, 3) + " kWh" : "---");

      display.setCursor(0, 26);
      display.print("CO2 Est  : ");
      display.print(pzemOk ? String(sessionEnergy * 0.82, 2) + " kg" : "---");

      display.setCursor(0, 38);
      display.print("Temp     : ");
      display.print(String(temperature, 1) + " \367C");  // °C

      display.setCursor(0, 50);
      display.print("Humidity : ");
      display.print(String(humidity, 0) + " %");
      break;

    // ── Screen 3: Occupancy & Relay ──────────────────────────
    case 3:
      display.setTextSize(1);
      display.setCursor(0, 0);  display.print("── STATUS ─────────");

      display.setCursor(0, 14);
      display.print("Motion   : ");
      display.print(motionDetected ? "DETECTED!" : "None");

      display.setCursor(0, 26);
      display.print("Light    : ");
      display.print(String(lightPercent) + "%");

      display.setCursor(0, 38);
      display.print("Relay    : ");
      display.print(relayState ? "ON" : "OFF");

      display.setCursor(0, 50);
      display.print("RSSI     : ");
      display.print(String(WiFi.RSSI()) + " dBm");
      break;
  }

  display.display();
}


// ═══════════════════════════════════════════════════════════════
//   🚀 SETUP
// ═══════════════════════════════════════════════════════════════
void setup() {
  // ── Serial Monitor (for debugging) ────────────────────────
  Serial.begin(115200);
  delay(100);
  Serial.println("\n\n╔══════════════════════════════════════╗");
  Serial.println(  "║  Green Campus EMS — Node Firmware    ║");
  Serial.println(  "║  IoT & AI Energy Management System   ║");
  Serial.println(  "╚══════════════════════════════════════╝");
  Serial.printf("Node ID: %s | Location: %s\n\n", NODE_ID, NODE_LOCATION);

  // ── Pin Modes ─────────────────────────────────────────────
  pinMode(PIN_PIR,   INPUT);
  pinMode(PIN_DHT,   INPUT_PULLUP); // Internal pull-up = no external 10kΩ resistor needed!
  pinMode(PIN_RELAY, OUTPUT);
  digitalWrite(PIN_RELAY, HIGH);  // Relay OFF at startup (active LOW)

  // ── OLED Initialization ───────────────────────────────────
  Wire.begin();
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDRESS)) {
    Serial.println("[OLED] ❌ Not found! Check wiring at D1(SCL) D2(SDA)");
    // Continue without OLED — not a fatal error
  } else {
    Serial.println("[OLED] ✅ Initialized");
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(10, 10); display.println("GreenCampus EMS");
    display.setCursor(10, 25); display.println("Initializing...");
    display.setCursor(10, 40); display.print("Node: "); display.println(NODE_ID);
    display.display();
    delay(1500);
  }

  // ── PZEM-004T Initialization ──────────────────────────────
  pzemSerial.begin(9600);
  Serial.println("[PZEM] SoftwareSerial started on D5/D6 @ 9600 baud");
  Serial.println("[PZEM] Waiting for first reading...");
  delay(1000); // Give PZEM time to wake up

  // ── DHT11 Initialization ──────────────────────────────────
  dht.begin();
  Serial.println("[DHT11] Started");

  // ── WiFi Connection ───────────────────────────────────────
  connectWiFi();

  // ── MQTT Setup ────────────────────────────────────────────
  mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setBufferSize(512);  // Increase buffer for larger JSON
  connectMQTT();

  Serial.println("\n[SETUP] ✅ Setup complete! Starting main loop...\n");
}


// ═══════════════════════════════════════════════════════════════
//   🔁 MAIN LOOP
// ═══════════════════════════════════════════════════════════════
void loop() {
  unsigned long now = millis();

  // ── Keep MQTT alive (process incoming messages) ────────────
  if (mqttClient.connected()) {
    mqttClient.loop();
  } else {
    // Reconnect MQTT every 5 seconds if disconnected
    if (now - lastReconnectAttempt > 5000) {
      lastReconnectAttempt = now;
      Serial.println("[MQTT] Disconnected — attempting reconnect...");
      if (WiFi.status() != WL_CONNECTED) {
        connectWiFi();
      }
      connectMQTT();
    }
  }

  // ── Read Sensors & Publish (every SENSOR_INTERVAL ms) ─────
  if (now - lastSensorRead >= SENSOR_INTERVAL) {
    lastSensorRead = now;

    readSensors();          // Read all sensors

    if (mqttClient.connected()) {
      publishEnergyData();  // Send PZEM data to dashboard
      publishEnvData();     // Send DHT11, PIR, LDR data
      checkAndPublishAlerts(); // Send alerts if thresholds exceeded
    }
  }

  // ── Rotate OLED Screen ────────────────────────────────────
  if (now - lastOledRotate >= OLED_ROTATE_MS) {
    lastOledRotate = now;
    oledScreen = (oledScreen + 1) % 4; // Cycle through 0,1,2,3
    updateOLED();
  }

  // ── Heartbeat (every 60 seconds) ──────────────────────────
  if (now - lastHeartbeat >= HEARTBEAT_INTERVAL) {
    lastHeartbeat = now;
    if (mqttClient.connected()) {
      publishStatus("online");
      Serial.println("[HEARTBEAT] ♥ Published");
    }
  }
}

/*
 * ════════════════════════════════════════════════════════════════
 *   📋 SETUP INSTRUCTIONS
 * ════════════════════════════════════════════════════════════════
 *
 * 1. INSTALL ARDUINO IDE + ESP8266 BOARD
 *    - Arduino IDE: https://www.arduino.cc/en/software
 *    - In IDE → File → Preferences → Additional Boards Manager URLs:
 *      https://arduino.esp8266.com/stable/package_esp8266com_index.json
 *    - Tools → Board → Boards Manager → search "esp8266" → Install
 *    - Tools → Board → NodeMCU 1.0 (ESP-12E Module)
 *    - Tools → Upload Speed → 115200
 *    - Tools → Port → COMx (your NodeMCU port)
 *
 * 2. INSTALL LIBRARIES (Tools → Manage Libraries)
 *    - Search and install each:
 *      ✅ PubSubClient         (by Nick O'Leary)
 *      ✅ PZEM004Tv30          (by Olexa Prokopenko)
 *      ✅ DHT sensor library   (by Adafruit)
 *      ✅ Adafruit GFX Library (by Adafruit)
 *      ✅ Adafruit SSD1306     (by Adafruit)
 *      ✅ ArduinoJson          (by Benoit Blanchon) — install v6.x
 *
 * 3. CONFIGURE FIRMWARE
 *    - Edit WIFI_SSID and WIFI_PASSWORD with your hotspot/WiFi
 *    - Find your laptop IP: open CMD → type "ipconfig"
 *      Look for IPv4 Address under "Wireless LAN adapter WiFi"
 *    - Set MQTT_SERVER to that IP address
 *    - Set NODE_ID to "node1" for first board, "node2" for second
 *    - Set NODE_LOCATION to room name (e.g. "Lab A", "Computer Lab")
 *
 * 4. INSTALL MOSQUITTO MQTT BROKER ON LAPTOP
 *    - Download: https://mosquitto.org/download/
 *    - Open CMD as Administrator → run: mosquitto -v
 *    - To allow remote connections, edit mosquitto.conf:
 *      Add: listener 1883
 *      Add: allow_anonymous true
 *    - Restart service
 *
 * 5. TEST MQTT (optional, in a new CMD window)
 *    - Subscribe: mosquitto_sub -t "campus/#" -v
 *    - You should see JSON data every 5 seconds
 *
 * 6. PZEM-004T WIRING (AC SAFETY)
 *    ⚠️  DANGER: AC mains is 230V. Do NOT touch live wires.
 *    - For demo: Use an extension cord
 *    - Cut the LIVE wire of the extension cord
 *    - Connect the two cut ends IN SERIES with PZEM current coil
 *    - Plug a desk lamp into the extension cord
 *    - PZEM voltage wires connect to L and N of the extension (not cut)
 *    - NEVER connect NodeMCU/breadboard to mains directly
 *    - If unsure: ask your lab technician to verify before powering on
 *
 * ════════════════════════════════════════════════════════════════
 */
