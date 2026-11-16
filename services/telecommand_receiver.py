from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from services.ground_station_api import GroundStationApiClient


class TelecommandReceiver(QObject):
    """Claims queued commands from PostgreSQL through the authenticated API."""

    command_received = pyqtSignal(dict)
    status_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, env_path: str = ".env", poll_interval_ms: int = 2000) -> None:
        super().__init__()
        self.client: GroundStationApiClient | None = None
        try:
            self.client = GroundStationApiClient(env_path)
        except Exception as exc:
            self.error_occurred.emit(f"Ground Station command client initialization failed: {exc}")

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_for_commands)
        self.poll_timer.setInterval(poll_interval_ms)
        self._poll_error_active = False

    @property
    def satellite_id(self) -> str:
        return self.client.satellite_id if self.client else "SAT-A"

    def set_satellite_id(self, satellite_id: str) -> None:
        if not self.client:
            raise RuntimeError("Ground Station command client is unavailable")
        self.client.set_satellite_id(satellite_id)
        self.status_message.emit(f"Command source changed to {satellite_id}.")

    @pyqtSlot()
    def start_polling(self) -> None:
        if self.client and not self.poll_timer.isActive():
            self.poll_timer.start()
            self.status_message.emit(f"Polling {self.client.satellite_id} command queue.")

    @pyqtSlot()
    def stop_polling(self) -> None:
        if self.poll_timer.isActive():
            self.poll_timer.stop()
            self.status_message.emit("Stopped polling for telecommands.")

    @pyqtSlot()
    def poll_for_commands(self) -> None:
        if not self.client:
            return
        try:
            commands = self.client.claim_commands(limit=10)
            if self._poll_error_active:
                self.status_message.emit("Ground Station command connection recovered.")
                self._poll_error_active = False
            for command in commands:
                self.command_received.emit(command)
        except Exception as exc:
            if not self._poll_error_active:
                self.error_occurred.emit(f"Error claiming Ground Station commands: {exc}")
                self._poll_error_active = True

    def acknowledge_command(self, command: dict, status: str = "SENT") -> None:
        if not self.client or not command.get("command_id"):
            return
        try:
            self.client.update_command_status(
                str(command["command_id"]),
                status.upper(),
                {"serial_bridge": "EDUSAT-ground-station"},
            )
        except Exception as exc:
            self.error_occurred.emit(f"Failed to update command status: {exc}")

    def close(self) -> None:
        self.stop_polling()
        self.status_message.emit("Ground Station command receiver closed.")
