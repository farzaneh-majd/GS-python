from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from services.ground_station_api import GroundStationApiClient


class TelemetryForwarder(QObject):
    """Forwards decoded board telemetry into the unified GS backend."""

    status_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, env_path: str = ".env") -> None:
        super().__init__()
        self.client: GroundStationApiClient | None = None
        try:
            self.client = GroundStationApiClient(env_path)
            ready = self.client.health()
            self.status_message.emit(
                f"Ground Station backend ready for {self.client.satellite_id}: "
                f"{ready.get('checks', {})}"
            )
        except Exception as exc:
            self.error_occurred.emit(f"Ground Station backend initialization failed: {exc}")

    @property
    def satellite_id(self) -> str:
        return self.client.satellite_id if self.client else "SAT-A"

    def set_satellite_id(self, satellite_id: str) -> None:
        if not self.client:
            raise RuntimeError("Ground Station backend client is unavailable")
        self.client.set_satellite_id(satellite_id)
        self.status_message.emit(f"Telemetry destination changed to {satellite_id}.")

    @pyqtSlot(dict)
    def forward(self, packet: dict) -> None:
        if not self.client:
            return
        try:
            result = self.client.ingest_telemetry(packet)
            self.status_message.emit(
                f"Stored {result['satellite_id']} telemetry {result['telemetry_id']} "
                f"as {result['record_id']}."
            )
        except Exception as exc:
            self.error_occurred.emit(f"Ground Station telemetry forwarding failed: {exc}")

    def close(self) -> None:
        self.status_message.emit("Ground Station telemetry forwarder closed.")
