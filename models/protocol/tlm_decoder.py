import struct
import json

ENDIAN = ">"   # big endian

FORMAT_MAP = {
    "u8": "B",
    "u16": "H",
    "u32": "I",
    "i8": "b",
    "i16": "h",
    "i32": "i",
    "f32": "f",
    "f64": "d"
}


class TelemetryDecoder:

    def __init__(self, map_file):
        with open(map_file) as f:
            self.map = json.load(f)["telemetry"]

        self.compiled = {}
        self._compile_formats()

    def _compile_formats(self):
        for tlm_id_hex, tlm in self.map.items():

            # normalize key (uppercase, zero padded)
            tlm_id_hex = tlm_id_hex.upper().zfill(4)

            if tlm["kind"] == "scalar":
                fmt = ENDIAN + FORMAT_MAP[tlm["format"]]
                fields = ["value"]

            elif tlm["kind"] == "struct":
                fmt = ENDIAN + "".join(FORMAT_MAP[f["format"]] for f in tlm["fields"])
                fields = [f["name"] for f in tlm["fields"]]

            else:
                continue

            self.compiled[tlm_id_hex] = {
                "name": tlm["name"],
                "struct": struct.Struct(fmt),
                "fields": fields,
                "enum": tlm.get("enum")
            }

    def decode_payload(self, payload):

        tlm_id_int = struct.unpack_from(ENDIAN + "H", payload, 0)[0]

        # convert to 4-digit hex string
        tlm_id_hex = f"{tlm_id_int:04X}"

        data = payload[2:]

        if tlm_id_hex not in self.compiled:
            raise ValueError(f"Unknown telemetry id {tlm_id_hex}")

        meta = self.compiled[tlm_id_hex]

        values = meta["struct"].unpack(data[:meta["struct"].size])

        if meta["fields"] == ["value"]:
            value = values[0]

            if meta["enum"]:
                value = meta["enum"].get(str(value), value)

            return {
                "tlm_id": tlm_id_hex,
                "name": meta["name"],
                "value": value
            }

        else:
            return {
                "tlm_id": tlm_id_hex,
                "name": meta["name"],
                "value": dict(zip(meta["fields"], values))
            }
