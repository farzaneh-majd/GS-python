from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


class TelecommandReceiver(QObject):
    """
    Polls an InfluxDB bucket for incoming telecommands intended for this CubeSat.
    Emits a Qt signal when a new command packet is received.
    """
    # Emitted when a new command is retrieved:
    # dict format: {"tc_id": str, "timestamp": int, "payload": str}
    command_received = pyqtSignal(dict)
    status_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, env_path: str = ".env", poll_interval_ms: int = 2000):
        super().__init__()

        # Load environment variables
        load_dotenv(env_path)
        shared_env_path = os.getenv("INFLUX_ENV_FILE", "").strip()
        if shared_env_path:
            shared_path = Path(shared_env_path)
            if not shared_path.is_absolute():
                shared_path = Path(env_path).resolve().parent / shared_path
            load_dotenv(shared_path, override=True)

        self.url = os.getenv("INFLUX_URL", "http://localhost:8086")
        self.token = os.getenv("INFLUX_TOKEN", "")
        self.org = os.getenv("INFLUX_ORG", "")
        # Using a dedicated bucket for commands, or fallback to telemetry
        self.bucket = os.getenv("INFLUX_TC_BUCKET") or os.getenv("INFLUX_BUCKET", "Telemetry")
        self.satellite_id = os.getenv("INFLUX_SATELLITE_ID", "cubesat-1")
        self.measurement = os.getenv("INFLUX_TC_MEASUREMENT", "commands")

        self.client: InfluxDBClient | None = None
        self.query_api = None
        self.write_api = None

        # Track the timestamp of the last command processed to avoid duplicate execution.
        # Initialized to look for commands generated in the last 5 minutes.
        self.last_processed_time = "-5m" 

        self._initialize_client()

        # Timer to poll the server database
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_for_commands)
        self.poll_timer.setInterval(poll_interval_ms)

    def _initialize_client(self) -> None:
        try:
            if not (self.url and self.token and self.org and self.bucket):
                raise ValueError(
                    "Missing InfluxDB config. Ensure INFLUX_URL, INFLUX_TOKEN, "
                    "INFLUX_ORG, INFLUX_TC_BUCKET exist in .env"
                )

            self.client = InfluxDBClient(url=self.url, token=self.token, org=self.org)
            self.query_api = self.client.query_api()
            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
            self.status_message.emit(
                f"InfluxDB Receiver initialized (bucket={self.bucket})."
            )
        except Exception as e:
            self.query_api = None
            self.client = None
            self.error_occurred.emit(f"Failed to connect InfluxDB Receiver: {e}")

    @pyqtSlot()
    def start_polling(self) -> None:
        if self.query_api and not self.poll_timer.isActive():
            self.poll_timer.start()
            self.status_message.emit("Started polling for telecommands.")

    @pyqtSlot()
    def stop_polling(self) -> None:
        if self.poll_timer.isActive():
            self.poll_timer.stop()
            self.status_message.emit("Stopped polling for telecommands.")

    def poll_for_commands(self) -> None:
        if not self.query_api:
            return

        # Flux Query to fetch commands for this satellite since the last processed timestamp
        # Filtered by satellite_id and command measurement fields
        query = f'''
        from(bucket: "{self.bucket}")
          |> range(start: {self.last_processed_time})
          |> filter(fn: (r) => r["_measurement"] == "{self.measurement}")
          |> filter(fn: (r) => r["satellite_id"] == "{self.satellite_id}")
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> filter(fn: (r) => r["status"] == "queued")
          |> sort(columns: ["_time"], desc: false)
          |> limit(n: 10)
        '''

        try:
            tables = self.query_api.query(query, org=self.org)
            new_commands = []

            for table in tables:
                for record in table.records:
                    record_time = record.get_time()
                    
                    # Construct command packet
                    cmd_packet = {
                        "command_id": record.values.get("command_id", "unknown"),
                        "satellite_id": record.values.get("satellite_id", self.satellite_id),
                        "timestamp": record_time.isoformat(),
                        "command_hex": record.values.get("command_hex", ""),
                    }
                    new_commands.append((record_time, cmd_packet))

            if new_commands:
                # Sort by time to process chronologically
                new_commands.sort(key=lambda x: x[0])
                
                for record_time, packet in new_commands:
                    # Emit command signal to the middleware logic (which sends to the CubeSat hardware)
                    self.command_received.emit(packet)
                
                # Update high-water mark time to avoid fetching these records next poll
                # InfluxDB query start range can accept absolute ISO8601 strings
                # Add a small buffer or offset if necessary to avoid boundary issues,
                # but standard practice is setting the range boundary past the last processed time.
                last_time = new_commands[-1][0]
                self.last_processed_time = (last_time + timedelta(microseconds=1)).isoformat()

        except Exception as e:
            self.error_occurred.emit(f"Error querying telecommands: {e}")

    def acknowledge_command(self, command: dict, status: str = "sent") -> None:
        if not self.write_api:
            return
        try:
            timestamp = datetime.fromisoformat(str(command["timestamp"]).replace("Z", "+00:00"))
            point = (
                Point(self.measurement)
                .tag("command_id", str(command["command_id"]))
                .tag("satellite_id", str(command.get("satellite_id", self.satellite_id)))
                .field("command_hex", str(command.get("command_hex", "")))
                .field("status", status)
                .time(timestamp, WritePrecision.NS)
            )
            self.write_api.write(bucket=self.bucket, org=self.org, record=point)
        except Exception as e:
            self.error_occurred.emit(f"Failed to acknowledge command: {e}")

    def close(self) -> None:
        self.stop_polling()
        try:
            if self.client:
                self.client.close()
                self.status_message.emit("InfluxDB receiver connection closed.")
        except Exception as e:
            self.error_occurred.emit(f"Error closing InfluxDB client: {e}")
