from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class TelemetryProcessor(QObject):
    packet_parsed = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    SYNC = b'\xDE\xAD\xBE\xEF'

    def __init__(self):
        super().__init__()
        self.buffer = bytearray()

    @staticmethod
    def compute_crc(data: bytes) -> int:
        crc = 0xFFFFFFFF

        for byte in data:
            crc ^= byte

            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xEDB88320
                else:
                    crc >>= 1

        return (~crc) & 0xFFFFFFFF


    @pyqtSlot(bytes)
    def process_raw_data(self, data: bytes):
        try:
            packets = self.feed(data)
            for pkt in packets:
                self.packet_parsed.emit(pkt)
        except Exception as e:
            self.error_occurred.emit(f"Telemetry processing error: {e}")

    def feed(self, data: bytes):
        self.buffer.extend(data)
        packets = []

        while True:
            sync_index = self.buffer.find(self.SYNC)

            if sync_index == -1:
                if len(self.buffer) > 1:
                    self.buffer = self.buffer[-3:]
                else:
                    self.buffer.clear()
                break

            if sync_index > 0:
                del self.buffer[:sync_index]

            # Minimum frame:
            # SYNC(4) + LEN(4) + Payload (N bytes) + CRC(4) = 13 bytes minimum
            if len(self.buffer) < 13:
                break

            payload_len = int.from_bytes(self.buffer[4:8])
            total_frame_len = 8 + payload_len + 4

            if len(self.buffer) < total_frame_len:
                break

            frame = bytes(self.buffer[:total_frame_len])
            del self.buffer[:total_frame_len]

            
            payload = frame[8:8 + payload_len]
            received_crc = frame[-4:]

            # Optional CRC check — currently not enforced
            # computed_crc = self.compute_crc(frame[:-1])
            # if computed_crc != received_crc:
            #     continue
            pkt = {
                "raw": frame,
                "length": payload_len,
                "payload": payload,
                "crc": received_crc,
            }
            packets.append(pkt)

        return packets


