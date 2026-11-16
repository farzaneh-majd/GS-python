from __future__ import annotations

import re


# Commands whose component handlers are registered by
# EDUSAT_Primary_OBC_v02.ino. Motor and system commands are intentionally not
# exposed because the current flight sketch does not register those handlers.
COMMAND_PRESETS: dict[str, str] = {
    "LED - Start blinking": "8401",
    "LED - Stop blinking": "8402",
    "AHT10 - Start conversion": "8601",
    "AHT10 - Stop conversion": "8602",
    "IMU - Start conversion": "8701",
    "IMU - Stop conversion": "8702",
    "Magnetometer - Start conversion": "8801",
    "Magnetometer - Stop conversion": "8802",
    "Solar cells - Start conversion": "8901",
    "Solar cells - Stop conversion": "8902",
}

SUPPORTED_COMMANDS = frozenset(COMMAND_PRESETS.values())


def normalize_command_hex(value: str) -> str:
    """Validate a no-argument EDUSAT command and return canonical HEX.

    The current flight handlers accept a two-byte opcode composed of a
    component ID and command ID. Rejecting arbitrary input is intentional:
    silently deleting invalid characters could transform a typo into a valid
    but unintended hardware command.
    """

    candidate = value.strip()
    if candidate.lower().startswith("0x"):
        candidate = candidate[2:]
    candidate = re.sub(r"[\s:_-]", "", candidate).upper()

    if not re.fullmatch(r"[0-9A-F]{4}", candidate):
        raise ValueError("Command must be exactly two HEX bytes, for example 8401")
    if candidate not in SUPPORTED_COMMANDS:
        raise ValueError(f"Unsupported command opcode: {candidate}")
    return candidate
