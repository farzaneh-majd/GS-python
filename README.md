# EDUSAT Ground Station (GS)

A Ground Station application built in Python to monitor and command the [EDUSAT](https://github.com/rohamkaveie/EDUSAT-flight-software-primary-version) satellite. This application serves as the bridge between raw radio telemetry and high-level data analytics.

## 🚀 Key Features
*   **Real-time Telemetry Parsing**: Decodes raw binary packets (`[SYNC][LEN][PAYLOAD][CRC32]`) into human-readable JSON formats using dynamic mapping.
*   **Twin-Satellite Database Integration**: Forwards processed telemetry through the authenticated Ground Station backend, which routes SAT-A and SAT-B into their independent InfluxDB instances and central PostgreSQL records.
*   **Modern UI**: A clean interface built with PyQt6, featuring packet monitors and firmware-aligned command presets.
*   **Threaded Communication**: Asynchronous serial port handling to ensure the UI remains responsive during high-frequency data bursts.
*   **Dynamic Protocol Mapping**: Easily update telemetry definitions via `telemetry_map.json` without recompiling the application.

## 🛠 Tech Stack
*   **Language**: Python 3.10+
*   **GUI Framework**: PyQt6
*   **Database path**: Ground Station API to SAT-A/SAT-B InfluxDB and PostgreSQL
*   **Configuration**: Dotenv (`.env`) for secure environment management
<!-- *   **Deployment**: Compiled via Nuitka for optimized executable size (<30MB) -->

## 📂 Project Structure
```text
EDUSAT_GS/
├── communication/   # Serial interface and background receiver threads
├── gui/            # Main window and custom UI components
├── protocol/       # Binary decoding logic and telemetry definitions
├── services/       # External integrations (InfluxDB, API Forwarders)
└── style/          # QSS stylesheets for UI customization
```

## ⚙️ Quick Start
1.  **Clone the repo**: `git clone https://github.com/your-username/EDUSAT_GS.git`
2.  **Create a python venv**: `python -m venv .venv`
3.  **Activate the venv**: `source .venv/bin/activate` in Linux or `.venv\Scripts\Activate.ps1` in Windows PowerShell. 
4.  **Install dependencies**: `pip install -r requirements.txt`
5.  **Configure environment**: Set `GROUND_STATION_URL`, `GROUND_STATION_ENV_FILE`, `GROUND_STATION_SATELLITE_ID`, and the optional serial auto-connect values in `.env`. The shared backend environment supplies the ingestion and command bridge keys without copying database credentials into this desktop application.
6.  **Run**: `python main.py`

## Ground Station Data Flow

```text
EDUSAT board -> serial frame decoder -> authenticated /ingest/packet
             -> SAT-A or SAT-B InfluxDB + PostgreSQL -> GraphQL dashboard

Dashboard command -> PostgreSQL queue -> authenticated bridge claim
                  -> EDUSAT serial writer -> command status in PostgreSQL
```

Select `SAT-A` or `SAT-B` before connecting the serial port. The selection is
locked while serial is connected so a physical stream cannot be routed to the
wrong satellite database accidentally.

## Supported Commands

The current flight sketch dispatches a two-byte opcode: the first byte is the
component ID and the second is the component command ID. The desktop command
selector exposes only handlers registered by `EDUSAT_Primary_OBC_v02.ino`:

| Command | HEX |
| --- | --- |
| LED start / stop blinking | `8401` / `8402` |
| AHT10 start / stop conversion | `8601` / `8602` |
| IMU start / stop conversion | `8701` / `8702` |
| Magnetometer start / stop conversion | `8801` / `8802` |
| Solar cells start / stop conversion | `8901` / `8902` |

`SENT` means the complete framed command was successfully written to the serial
port. The current flight firmware does not return a dedicated command
acknowledgement packet, so `ACKNOWLEDGED` must only be used after a future
firmware acknowledgement mechanism is implemented. Resulting telemetry can be
used as operational evidence that a command took effect.
