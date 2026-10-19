"""Pilote BLE expérimental du Zwift Ride (firmware observé 1.1.0).

Une instance de ZwiftRideDriver représente UNE unité (left ou right).
Pour utiliser les deux côtés, lancer deux instances en parallèle : chaque unité
a sa connexion BLE, son handshake, sa clé, son IV et son état de boutons.

Le protocole et les bits sont issus de captures réelles fournies avec le projet.
Les fonctions inconnues et les bits non vérifiés sont volontairement ignorés.
"""
import asyncio
from dataclasses import replace

from bleak import BleakScanner, BleakClient
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDH, SECP256R1, EllipticCurvePublicKey, generate_private_key)
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from events import DeviceEvent, EventType
from .base import CompatibilityStatus, ConnectionState, DeviceDriver, DeviceInfo

BASE = "-19ca-4651-86e5-fa29dcdd09d1"
def uuid(n):
    return f"0000000{n}{BASE}"

ASYNC = uuid(2)       # notify : messages chiffrés
SYNC_RX = uuid(3)     # write : handshake client -> appareil
SYNC_TX = uuid(4)     # indicate : réponse du handshake
MANUFACTURER_ID = 0x094A
LEFT_MARKER = 0x08
RIGHT_MARKER = 0x07
BATTERY_TYPE = 0x19
BUTTONS_TYPE = 0x23
IDLE_TYPE = 0x15

# bit, événement logique, côté attendu
BUTTONS = {
    0x0001: ("LEFT", "left"),
    0x0002: ("UP", "left"),
    0x0004: ("RIGHT", "left"),
    0x0008: ("DOWN", "left"),
    0x0100: ("SHIFT_UP_L", "left"),
    0x0200: ("SHIFT_DN_L", "left"),
    0x0010: ("A", "right"),
    0x0020: ("B", "right"),
    0x0040: ("Y", "right"),
    0x0080: ("Z", "right"),
    0x1000: ("SHIFT_UP_R", "right"),
    0x2000: ("SHIFT_DN_R", "right"),
}

EVENTS = {
    "LEFT": (EventType.RIDE_LEFT_DOWN, EventType.RIDE_LEFT_UP),
    "UP": (EventType.RIDE_UP_DOWN, EventType.RIDE_UP_UP),
    "RIGHT": (EventType.RIDE_RIGHT_DOWN, EventType.RIDE_RIGHT_UP),
    "DOWN": (EventType.RIDE_DOWN_DOWN, EventType.RIDE_DOWN_UP),
    "A": (EventType.RIDE_A_DOWN, EventType.RIDE_A_UP),
    "B": (EventType.RIDE_B_DOWN, EventType.RIDE_B_UP),
    "Y": (EventType.RIDE_Y_DOWN, EventType.RIDE_Y_UP),
    "Z": (EventType.RIDE_Z_DOWN, EventType.RIDE_Z_UP),
    "SHIFT_UP_L": (EventType.RIDE_SHIFT_UP_L_DOWN, EventType.RIDE_SHIFT_UP_L_UP),
    "SHIFT_DN_L": (EventType.RIDE_SHIFT_DN_L_DOWN, EventType.RIDE_SHIFT_DN_L_UP),
    "SHIFT_UP_R": (EventType.RIDE_SHIFT_UP_R_DOWN, EventType.RIDE_SHIFT_UP_R_UP),
    "SHIFT_DN_R": (EventType.RIDE_SHIFT_DN_R_DOWN, EventType.RIDE_SHIFT_DN_R_UP),
}


def parse_varint(buf, offset):
    value = 0
    shift = 0
    while offset < len(buf) and shift <= 63:
        byte = buf[offset]
        offset += 1
        value |= (byte & 0x7f) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    raise ValueError("varint protobuf tronqué ou trop long")


def parse_fields(buf):
    """Décode les champs protobuf en préservant les champs répétés."""
    fields = {}
    i = 0
    while i < len(buf):
        tag, i = parse_varint(buf, i)
        number, wire = tag >> 3, tag & 7
        if number == 0:
            raise ValueError("numéro de champ protobuf invalide")
        if wire == 0:
            value, i = parse_varint(buf, i)
        elif wire == 1:
            if i + 8 > len(buf):
                raise ValueError("champ protobuf fixed64 tronqué")
            value, i = buf[i:i + 8], i + 8
        elif wire == 2:
            length, i = parse_varint(buf, i)
            if length < 0 or i + length > len(buf):
                raise ValueError("champ protobuf length-delimited tronqué")
            value, i = bytes(buf[i:i + length]), i + length
        elif wire == 5:
            if i + 4 > len(buf):
                raise ValueError("champ protobuf fixed32 tronqué")
            value, i = buf[i:i + 4], i + 4
        else:
            raise ValueError(f"wire type protobuf non pris en charge : {wire}")
        if number in fields:
            if not isinstance(fields[number], list):
                fields[number] = [fields[number]]
            fields[number].append(value)
        else:
            fields[number] = value
    return fields


def _one(fields, number, default=None):
    value = fields.get(number, default)
    return value[-1] if isinstance(value, list) else value


def decode_button_message(payload):
    """Retourne (mask, [(location, value), ...]) pour un payload de type 0x23."""
    fields = parse_fields(payload)
    mask = _one(fields, 1)
    if not isinstance(mask, int):
        raise ValueError("masque de boutons absent ou invalide")
    paddles = []
    nested = fields.get(3, [])
    if not isinstance(nested, list):
        nested = [nested]
    for raw in nested:
        if not isinstance(raw, bytes):
            continue
        sub = parse_fields(raw)
        location, value = _one(sub, 1), _one(sub, 2)
        if isinstance(location, int) and isinstance(value, int) and 0 <= value <= 200:
            paddles.append((location, value))
    return mask & 0xffffffff, paddles


class RideCrypto:
    """Handshake ECDH P-256 et déchiffrement AES-CCM observés sur le Ride."""
    def __init__(self):
        self.private_key = generate_private_key(SECP256R1())
        self.client_pub64 = self.private_key.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint)[1:]
        self.key = None
        self.iv = None

    def hello(self):
        return b"RideOn\x01\x02" + self.client_pub64

    def accept(self, data):
        data = bytes(data)
        # Les deux octets après RideOn diffèrent du Click V1 (Ride : 02 01).
        if len(data) != 72 or data[:6] != b"RideOn":
            return False
        device_pub64 = data[8:72]
        public_key = EllipticCurvePublicKey.from_encoded_point(
            SECP256R1(), b"\x04" + device_pub64)
        secret = self.private_key.exchange(ECDH(), public_key)
        material = HKDF(
            algorithm=hashes.SHA256(), length=36,
            salt=device_pub64 + self.client_pub64, info=b""
        ).derive(secret)
        self.key, self.iv = material[:32], material[32:]
        return True

    def decrypt(self, frame):
        if self.key is None or self.iv is None:
            raise ValueError("handshake non terminé")
        if len(frame) < 9:
            raise ValueError("trame chiffrée trop courte")
        counter = frame[:4]
        nonce = self.iv + counter
        return AESCCM(self.key, tag_length=4).decrypt(nonce, frame[4:], None)


class ZwiftRideDriver(DeviceDriver):
    """Pilote d'une seule unité Zwift Ride : side='left' ou side='right'."""
    device_type = "zwift_ride"

    def __init__(self, side, verbose=lambda: False, status=lambda *args: None,
                 battery=lambda value: None, log=lambda value: None,
                 diagnostic=lambda *args: None, tick=lambda: None):
        if side not in ("left", "right"):
            raise ValueError("side doit être 'left' ou 'right'")
        self.side = side
        self.marker = LEFT_MARKER if side == "left" else RIGHT_MARKER
        self.verbose, self.status = verbose, status
        self.battery, self.log, self.diagnostic, self.tick = battery, log, diagnostic, tick
        self.crypto = None
        self.ready = False
        self.emit_event = None
        self.state = {name: False for name, unit in BUTTONS.values() if unit == side}
        self.last_paddle = None
        self.last_battery = None
        self.last_error = None
        self.device_address = ""
        self.info = DeviceInfo(
            self.device_type, f"Zwift Ride ({side})", "Zwift",
            capabilities=frozenset(self._capabilities()))

    def _capabilities(self):
        return [name.lower() for name, unit in BUTTONS.values() if unit == self.side] + [
            "battery", "analog_paddle"]

    def get_device_info(self):
        return self.info

    def matches(self, device, advertisement):
        data = getattr(advertisement, "manufacturer_data", {}).get(MANUFACTURER_ID, b"")
        if not data or data[0] not in (LEFT_MARKER, RIGHT_MARKER):
            return False
        return data[0] == self.marker

    def _matches(self, device, advertisement):
        return self.matches(device, advertisement)

    async def detect(self):
        self.info = replace(self.info, connection_state=ConnectionState.SCANNING)
        try:
            device = await BleakScanner.find_device_by_filter(self._matches, timeout=30)
        except Exception:
            self.info = replace(self.info, connection_state=ConnectionState.ERROR)
            raise
        if device is None:
            self.info = replace(self.info, connection_state=ConnectionState.DISCONNECTED)
        return device

    def _emit_button(self, name, pressed, wire_payload=None, plaintext=None):
        down, up = EVENTS[name]
        event_type = down if pressed else up
        self.emit_event(DeviceEvent(event_type, device_id=f"zwift_ride_{self.side}"),
                        wire_payload, plaintext)

    def _release_all(self):
        for name, pressed in tuple(self.state.items()):
            if pressed:
                self._emit_button(name, False)
            self.state[name] = False

    async def run(self, device, emit):
        self.emit_event = emit
        self.crypto = RideCrypto()
        self.ready = False
        self.state = {name: False for name, unit in BUTTONS.values() if unit == self.side}
        self.last_paddle = None
        self.device_address = getattr(device, "address", "")
        self.info = DeviceInfo(
            self.device_type, f"Zwift Ride ({self.side})", "Zwift",
            self.device_address, capabilities=frozenset(self._capabilities()),
            connection_state=ConnectionState.CONNECTING)
        self.status(f"Zwift Ride {self.side} trouvé, connexion…", "orange")
        result = (f"Zwift Ride {self.side} déconnecté", "orange")
        try:
            async with BleakClient(device) as client:
                self.info = replace(self.info, connection_state=ConnectionState.CONNECTED)
                self.log(f"Zwift Ride {self.side} connecté à {self.device_address}")
                await client.start_notify(ASYNC, self.on_async)
                await client.start_notify(SYNC_TX, self.on_sync_tx)
                await client.write_gatt_char(SYNC_RX, self.crypto.hello(), response=True)
                self.status(f"Zwift Ride {self.side} : échange des clés…", "orange")
                waited = 0.0
                while client.is_connected:
                    await asyncio.sleep(0.1)
                    waited += 0.1
                    self.tick()
                    if not self.ready and waited > 15:
                        msg = ("Handshake Zwift Ride impossible : vérifie que cette unité "
                               "n'est pas déjà connectée à une autre application et que le "
                               "firmware correspond au protocole observé (1.1.0).")
                        self.info = replace(
                            self.info, connection_state=ConnectionState.ERROR,
                            compatibility=CompatibilityStatus.INCOMPATIBLE)
                        self.log(msg)
                        result = (msg, "red")
                        break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.info = replace(
                self.info, connection_state=ConnectionState.ERROR,
                compatibility=(CompatibilityStatus.INCOMPATIBLE if not self.ready
                               else self.info.compatibility))
            self.log(f"Zwift Ride {self.side} : erreur Bluetooth : {exc}")
            self.status(f"Zwift Ride {self.side} : erreur Bluetooth, nouvelle tentative…", "red")
            raise
        finally:
            self._release_all()
            self.info = replace(
                self.info, connection_state=(
                    ConnectionState.ERROR if self.info.compatibility == CompatibilityStatus.INCOMPATIBLE
                    else ConnectionState.DISCONNECTED),
                compatibility=(CompatibilityStatus.COMPATIBLE if self.ready
                               else self.info.compatibility))
        self.log(f"Zwift Ride {self.side} déconnecté")
        return result

    def on_sync_tx(self, _sender, data):
        try:
            if self.crypto and self.crypto.accept(bytes(data)):
                self.log(f"Clé de l'unité Zwift Ride {self.side} reçue")
        except Exception as exc:
            self.last_error = str(exc)
            self.log(f"Handshake Ride invalide ({self.side}) : {exc}")

    def on_async(self, _sender, data):
        frame = bytes(data)
        try:
            if len(frame) >= 9:
                # Les compteurs 0 et 1 peuvent arriver avant la réponse au handshake.
                if not self.crypto or self.crypto.key is None:
                    return
                plaintext = self.crypto.decrypt(frame)
                if not self.ready:
                    self.ready = True
                    self.last_error = None
                    self.info = replace(
                        self.info, connection_state=ConnectionState.CONNECTED,
                        compatibility=CompatibilityStatus.COMPATIBLE)
                    self.status(f"Zwift Ride {self.side} connecté : prêt", "green")
            else:
                plaintext = frame
            self.handle(plaintext, frame)
        except Exception as exc:
            self.last_error = str(exc)
            if self.verbose():
                self.log(f"Trame Ride illisible ({self.side}) : {frame.hex()} ({exc})")
                self.diagnostic(ASYNC, frame.hex(), "", "UNREADABLE", "—")

    def handle(self, plaintext, wire_payload=None):
        if not plaintext:
            return
        msg_type, payload = plaintext[0], plaintext[1:]
        if self.verbose():
            self.log(f"Ride {self.side}: type={msg_type:#04x} brut={plaintext.hex()}")

        if msg_type == BATTERY_TYPE:
            fields = parse_fields(payload)
            pct = _one(fields, 2)
            if isinstance(pct, int) and 0 <= pct <= 100:
                self.battery(pct)
                self.last_battery = pct
            elif self.verbose():
                self.log(f"Batterie Ride invalide ignorée : {pct!r}")
        elif msg_type == BUTTONS_TYPE:
            try:
                mask, paddles = decode_button_message(payload)
            except ValueError as exc:
                if self.verbose():
                    self.log(f"Message boutons Ride invalide : {exc}")
                return
            for bit, (name, unit) in BUTTONS.items():
                if unit != self.side:
                    continue
                pressed = not bool(mask & bit)
                previous = self.state[name]
                if pressed != previous:
                    self.state[name] = pressed
                    self._emit_button(name, pressed, wire_payload, plaintext)

            expected_location = 0 if self.side == "left" else 1
            for location, value in paddles:
                if location != expected_location:
                    continue
                if value != self.last_paddle:
                    self.last_paddle = value
                    self.emit_event(
                        DeviceEvent(EventType.RIDE_PADDLE,
                                    device_id=f"zwift_ride_{self.side}",
                                    value=value),
                        wire_payload, plaintext)
        elif msg_type == IDLE_TYPE:
            return
        elif self.verbose():
            # Le type 0x2A est volontairement laissé sans interprétation.
            self.diagnostic(ASYNC, wire_payload.hex() if wire_payload else "",
                            plaintext.hex(), f"UNKNOWN_TYPE_{msg_type:#04x}", "—")
