from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from dotenv import load_dotenv

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


_PRECISION_MAP = {
    "ns": WritePrecision.NS,
    "us": WritePrecision.US,
    "ms": WritePrecision.MS,
    "s":  WritePrecision.S,
}


def _safe_field_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", value)


def _dashboard_tlm_id(value: object) -> str:
    """Convert the decoder's zero-padded hexadecimal ID to the dashboard ID."""
    text = str(value)
    if re.fullmatch(r"[0-9A-Fa-f]{4}", text):
        return str(int(text, 16))
    return text


def _decoded_values(packet: dict) -> dict[str, object]:
    value = packet.get("value")
    if isinstance(value, dict):
        return value
    return {str(packet.get("name", "value")): value}


class TelemetryForwarder(QObject):
    status_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, env_path: str = ".env"):
        super().__init__()

        # Load .env (safe to call multiple times)
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
        self.bucket = os.getenv("INFLUX_BUCKET", "")
        
        self.measurement = os.getenv("INFLUX_MEASUREMENT", "raw_telemetry")
        self.satellite_id = os.getenv("INFLUX_SATELLITE_ID", "CUBESAT_01")

        precision_str = os.getenv("INFLUX_TIME_PRECISION", "ms").lower().strip()
        self.time_precision = _PRECISION_MAP.get(precision_str, WritePrecision.MS)
        
        self.client: InfluxDBClient | None = None
        self.write_api = None

        self._initialize_client()

    def _initialize_client(self) -> None:
        try:
            if not (self.url and self.token and self.org and self.bucket):
                raise ValueError(
                    "Missing InfluxDB config. Ensure INFLUX_URL, INFLUX_TOKEN, "
                    "INFLUX_ORG, INFLUX_BUCKET exist in .env"
                )

            self.client = InfluxDBClient(url=self.url, token=self.token, org=self.org)
            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
            self.status_message.emit(
                f"InfluxDB Forwarder initialized (bucket={self.bucket}, org={self.org})."
            )
        except Exception as e:
            
            self.write_api = None
            self.client = None
            self.error_occurred.emit(f"Failed to connect to InfluxDB: {e}")

    @pyqtSlot(dict)
    def forward(self, packet: dict) -> None:
        """
        Writes the schema consumed by the sibling Next.js ground station.

        Expected decoded packet format:
          {
            "tlm_id": int | str,
            "timestamp": int,   # unix time in precision matching INFLUX_TIME_PRECISION (default ms)
            "data": bytes | bytearray | str,
            "name": str,
            "value": scalar | dict
          }
        """
        if not self.write_api:
            return

        try:
            tlm_id = _dashboard_tlm_id(packet.get("tlm_id", "unknown"))
            ts = packet.get("timestamp", None)
            payload = packet.get("data", b"")

            if ts is None:
                raise ValueError("packet missing required field: 'timestamp'")

            # store payload as a string field (Influx fields cannot be raw bytes)
            if isinstance(payload, (bytes, bytearray)):
                payload_str = payload.hex()
            else:
                payload_str = str(payload)

            values = _decoded_values(packet)
            record_id = uuid.uuid4().hex
            point = (
                Point(self.measurement)
                .tag("record_id", record_id)
                .tag("satellite_id", self.satellite_id)
                .tag("tlm_id", tlm_id)
                .field("payload", payload_str)
                .field("telemetry_name", str(packet.get("name", f"Telemetry {tlm_id}")))
                .field("decoded_json", json.dumps(values, separators=(",", ":")))
                .field("payload_byte_length", len(payload_str) // 2)
                .time(int(ts), self.time_precision)
            )

            for name, value in values.items():
                if isinstance(value, (bool, int, float, str)):
                    point.field(_safe_field_name(str(name)), value)

            self.write_api.write(bucket=self.bucket, org=self.org, record=point)

        except Exception as e:
            self.error_occurred.emit(f"InfluxDB Write Error: {e}")

    def close(self) -> None:
        try:
            if self.client:
                self.client.close()
                self.status_message.emit("InfluxDB connection closed.")
        except Exception as e:
            self.error_occurred.emit(f"Error closing InfluxDB client: {e}")
