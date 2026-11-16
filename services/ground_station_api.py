from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


VALID_SATELLITES = ("SAT-A", "SAT-B")


def _load_configuration(env_path: str) -> None:
    load_dotenv(env_path)
    shared_env = os.getenv("GROUND_STATION_ENV_FILE", "").strip()
    if not shared_env:
        return
    shared_path = Path(shared_env)
    if not shared_path.is_absolute():
        shared_path = Path(env_path).resolve().parent / shared_path
    load_dotenv(shared_path, override=False)


class GroundStationApiError(RuntimeError):
    pass


class GroundStationApiClient:
    """Authenticated adapter between the serial bridge and GS backend.

    Database routing stays inside the backend.  Selecting SAT-A or SAT-B here
    determines which InfluxDB instance receives telemetry and which PostgreSQL
    command queue is consumed.
    """

    def __init__(self, env_path: str = ".env") -> None:
        _load_configuration(env_path)
        self.base_url = os.getenv("GROUND_STATION_URL", "http://localhost:8000").rstrip("/")
        self.ingest_api_key = os.getenv("GS_INGEST_API_KEY") or os.getenv("INGEST_API_KEY", "")
        self.command_api_key = os.getenv("GS_COMMAND_API_KEY") or os.getenv("COMMAND_API_KEY", "")
        self.timeout = float(os.getenv("GROUND_STATION_TIMEOUT_SECONDS", "5"))
        self.satellite_id = "SAT-A"
        self.set_satellite_id(os.getenv("GROUND_STATION_SATELLITE_ID", "SAT-A"))

        if not self.ingest_api_key:
            raise GroundStationApiError("Missing GS ingest API key")
        if not self.command_api_key:
            raise GroundStationApiError("Missing GS command API key")

    def set_satellite_id(self, satellite_id: str) -> None:
        normalized = satellite_id.strip().upper()
        if normalized not in VALID_SATELLITES:
            raise ValueError("Satellite must be SAT-A or SAT-B")
        self.satellite_id = normalized

    def _request(self, path: str, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "X-API-Key": api_key},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise GroundStationApiError(f"Backend HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise GroundStationApiError(f"Backend connection failed: {exc.reason}") from exc

    def health(self) -> dict[str, Any]:
        request = Request(f"{self.base_url}/health/ready", method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError) as exc:
            raise GroundStationApiError(f"Backend readiness check failed: {exc}") from exc

    def ingest_telemetry(self, packet: dict[str, Any]) -> dict[str, Any]:
        telemetry_text = str(packet.get("tlm_id", ""))
        if re.fullmatch(r"[0-9A-Fa-f]{4}", telemetry_text):
            telemetry_id = str(int(telemetry_text, 16))
        else:
            telemetry_id = telemetry_text

        raw_data = packet.get("data", b"")
        if isinstance(raw_data, (bytes, bytearray)):
            payload = bytes(raw_data).hex().upper()
        else:
            payload = re.sub(r"[^0-9A-Fa-f]", "", str(raw_data)).upper()

        timestamp = packet.get("received_at")
        if not timestamp:
            timestamp = datetime.now(timezone.utc).isoformat()

        return self._request(
            "/ingest/packet",
            {
                "satellite_id": self.satellite_id,
                "telemetry_id": telemetry_id,
                "payload": payload,
                "timestamp": timestamp,
            },
            self.ingest_api_key,
        )

    def claim_commands(self, limit: int = 10) -> list[dict[str, Any]]:
        response = self._request(
            "/bridge/commands/claim",
            {"satellite_id": self.satellite_id, "limit": limit},
            self.command_api_key,
        )
        return list(response.get("commands", []))

    def update_command_status(
        self,
        command_id: str,
        status: str,
        response: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            f"/bridge/commands/{command_id}/status",
            {"status": status.upper(), "response": response or {}},
            self.command_api_key,
        )
