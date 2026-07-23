SYNC_BYTE = 0xDEADBEEF


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


def build_command_packet(opcode: bytes, args: bytes = b"") -> bytes:
    """
    Packet format:
    [SYNC][LEN][DATA...][CRC]

    DATA = [OPCODE][ARGS...]
    """

    data = opcode + args
    
    length = len(data)

    # packet = bytes([SYNC_BYTE>>8, SYNC_BYTE & 0xff, length]) + data

    packet = bytes([(length>>24)&0xff, (length>>16)&0xff, (length>>8)&0xff, (length)&0xff]) + data

    crc = compute_crc(packet)
    crc = bytes([(crc>>24)&0xff,(crc>>16)&0xff,(crc>>8)&0xff,(crc)&0xff])


    packet = bytes([(SYNC_BYTE>>24)&0xff, (SYNC_BYTE>>16) & 0xff,(SYNC_BYTE>>8)&0xff, SYNC_BYTE & 0xff]) + packet + crc

    return packet
