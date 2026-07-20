from __future__ import annotations

import os
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient


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

        self.url = os.getenv("INFLUX_URL", "http://localhost:8086")
        self.token = os.getenv("INFLUX_TOKEN", "")
        self.org = os.getenv("INFLUX_ORG", "")
        # Using a dedicated bucket for commands, or fallback to telemetry
        self.bucket = os.getenv("INFLUX_TC_BUCKET", "telecommands")
        self.satellite_id = os.getenv("INFLUX_SATELLITE_ID", "CUBESAT_01")
        self.measurement = os.getenv("INFLUX_TC_MEASUREMENT", "commands")

        self.client: InfluxDBClient | None = None
        self.query_api = None

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
          |> sort(columns: ["_time"], desc: false)
        '''

        try:
            tables = self.query_api.query(query, org=self.org)
            new_commands = []

            for table in tables:
                for record in table.records:
                    record_time = record.get_time()
                    
                    # Construct command packet
                    cmd_packet = {
                        "tc_id": record.values.get("tc_id", "unknown"),
                        "timestamp": record_time.isoformat(),
                        # The command payload could be hex encoded or plain text parameters
                        "payload": record.values.get("payload", ""),
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
                self.last_processed_time = last_time.isoformat()

        except Exception as e:
            self.error_occurred.emit(f"Error querying telecommands: {e}")

    def close(self) -> None:
        self.stop_polling()
        try:
            if self.client:
                self.client.close()
                self.status_message.emit("InfluxDB receiver connection closed.")
        except Exception as e:
            self.error_occurred.emit(f"Error closing InfluxDB client: {e}")
