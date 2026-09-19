import os
import re
import math
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

# Import Models
from models.serial_interface import SerialInterface
from models.receiver_thread import ReceiverThread
from models.telemetry_processor import TelemetryProcessor
from models.protocol.command_packet import build_command_packet
from services.telemetry_forwarder import TelemetryForwarder
from services.telecommand_receiver import TelecommandReceiver
from models.protocol.tlm_decoder import TelemetryDecoder
from datetime import datetime
# from models.command_receiver import CommandReceiver

class GroundStationController(QObject):
    # Signals for the View (MainWindow) to listen to
    status_message = pyqtSignal(str)
    error_message = pyqtSignal(str)
    raw_data_received = pyqtSignal(bytes)
    packet_received = pyqtSignal(dict)
    command_fetched = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        # 1. Instantiate Models
        self.serial_interface = SerialInterface()
        self.telemetry_processor = TelemetryProcessor()
        self.telemetry_forwarder = TelemetryForwarder()
        self.command_receiver = TelecommandReceiver()
        self.decoder = TelemetryDecoder("./models/protocol/telemetry_map.json")
        self.receiver_thread = None

        # 2. Internal Signal Wiring (Data Pipeline)

        # received serial data go to telemetry_processor to get parsed
        self.raw_data_received.connect(self._handle_received_data)


        # Processed packets go to: 1. GUI (via signal) and 2. Database (Forwarder)
        self.telemetry_processor.packet_parsed.connect(self._handle_parsed_packet)
        self.telemetry_processor.error_occurred.connect(self.error_message.emit)



        # Connect Forwarder & CommandReceiver feedback to general status signals
        self.telemetry_forwarder.status_message.connect(self.status_message.emit)
        self.telemetry_forwarder.error_occurred.connect(self.error_message.emit)
        self.command_receiver.command_received.connect(self.handle_server_command)
        self.command_receiver.status_message.connect(self.status_message.emit)
        self.command_receiver.error_occurred.connect(self.error_message.emit)
        
        # self.command_receiver.status_messags
        self.status_message.emit("System Controller initialized.")

    # --- Connection Logic ---

    def getListPorts(self):
        return self.serial_interface.list_ports()


    def connect_serial(self, port: str, baudrate: int):
        if self.serial_interface.is_connected():
            return True

        if not port:
            self.error_message.emit("No serial port is available. Turn Bluetooth on, refresh ports, and select a port.")
            return False

        try:
            self.serial_interface.connect(port, baudrate)
            
            # Start Receiver Thread
            # We pass the processor so the thread can feed it data
            self.receiver_thread = ReceiverThread(self.serial_interface)
            
            # Connect Thread signals to Controller signals
            self.receiver_thread.raw_received.connect(self.raw_data_received.emit)
            self.receiver_thread.status_message.connect(self.status_message.emit)
            self.receiver_thread.error_occurred.connect(self.error_message.emit)
            
            self.receiver_thread.start()
            
            # Poll after the window has finished connecting so a database or
            # Bluetooth delay cannot block the Connect button handler.
            self.command_receiver.start_polling()

            self.status_message.emit(f"Connected to {port}. Threads started.")
            return True

        except Exception as e:
            self.error_message.emit(f"Connection error: {e}")
            return False

    def disconnect_serial(self):
        if self.receiver_thread and self.receiver_thread.isRunning():
            self.receiver_thread.stop()
            self.receiver_thread.wait()
        
        if self.serial_interface.is_connected():
            self.serial_interface.disconnect()
        
        self.command_receiver.stop_polling()
            
        self.status_message.emit("Disconnected.")

    def is_connected(self):
        return self.serial_interface.is_connected()

    # --- Data Routing ---

    @pyqtSlot(dict)
    def _handle_parsed_packet(self, packet: dict):
        """Routes parsed data to GUI and InfluxDB."""
        # decode the payload (extracting tlm_id,timestamp,data)

        try:
            decoded = self.decoder.decode_payload(packet["payload"])
        except Exception as e:
            self.log(f"Decode Error: {e}")
            return
        packet["decoded"] = decoded


        # temprorary replace cubesat timestamp with local machine timestamp
        packet["decoded"]["timestamp"] = math.floor(datetime.now().timestamp() * 1000)

        # Send to View
        self.packet_received.emit(packet)
        # Send to InfluxDB
        self.telemetry_forwarder.forward(packet["decoded"])

    @pyqtSlot(bytes)
    def _handle_received_data(self, data:bytes):
        self.telemetry_processor.process_raw_data(data)

    @pyqtSlot(dict)
    def handle_server_command(self, command: dict):
        """Processes a command received from the Web Server API."""
        self.command_fetched.emit(command) # Notify GUI for the log
        
        if not self.is_connected():
            self.error_message.emit("Command received but Serial is disconnected.")
            return

        # Simple Packet Builder logic (Can be moved to a helper function)
        try:
            command_hex = re.sub(r'[^0-9A-Fa-f]', '', str(command.get("command_hex", "")))
            if not command_hex or len(command_hex) % 2:
                raise ValueError("Server command must contain complete HEX bytes")
            full_packet = build_command_packet(bytes.fromhex(command_hex))
            self.serial_interface.write(full_packet)
            self.command_receiver.acknowledge_command(command, "sent")
            self.status_message.emit(
                f"Server command {command['command_id']} sent to serial: {full_packet.hex().upper()}"
            )
                
        except Exception as e:
            if command.get("command_id"):
                self.command_receiver.acknowledge_command(command, "failed")
            self.error_message.emit(f"Failed to send server command: {e}")

    def sendCommand(self, hex_text: str):

        if not self.serial_interface.is_connected():
            self.status_message.emit("Cannot send: not connected.")
            return

        try:

            clean_hex = re.sub(r'[^0-9A-Fa-f]', '', hex_text)
            
            if len(clean_hex) % 2 != 0:
                raise ValueError("Hex string must contain full bytes")

            cmd_opcode = bytes.fromhex(clean_hex)

            packet = build_command_packet(cmd_opcode)
            self.serial_interface.write(packet)
            self.status_message.emit(f"Sent Packet: {packet}")
        except Exception as e:
            self.error_message.emit(f"Send error: {e}")

    def cleanup(self):
        self.disconnect_serial()
        self.command_receiver.close()
        self.telemetry_forwarder.close()
