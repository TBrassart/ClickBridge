"""Pilote BLE et protocole chiffré du Zwift Click V1."""
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
from .base import (CompatibilityStatus, ConnectionState, DeviceDriver, DeviceInfo)

BASE = "-19ca-4651-86e5-fa29dcdd09d1"
def u(n): return f"0000000{n}{BASE}"
ASYNC, SYNC_RX, SYNC_TX = u(2), u(3), u(4)
CLICK_TYPE, BATTERY_TYPE = 0x37, 0x19
DEVICE_NAME_PREFIX = "Zwift Click"


def parse_pb(buf):
    """Mini décodeur protobuf : {numéro_de_champ: valeur}."""
    out, i = {}, 0
    def varint(i):
        shift = val = 0
        while True:
            b = buf[i]; i += 1
            val |= (b & 0x7F) << shift
            if not b & 0x80:
                return val, i
            shift += 7
    try:
        while i < len(buf):
            tag, i = varint(i)
            f, w = tag >> 3, tag & 7
            if w == 0:
                out[f], i = varint(i)
            elif w == 2:
                n, i = varint(i); out[f] = bytes(buf[i:i + n]); i += n
            elif w == 5:
                out[f] = bytes(buf[i:i + 4]); i += 4
            elif w == 1:
                out[f] = bytes(buf[i:i + 8]); i += 8
            else:
                break
    except IndexError:
        pass
    return out


class ClickCrypto:
    """Échange ECDH + AES-CCM du protocole Click V1."""
    def __init__(self):
        self.priv = generate_private_key(SECP256R1())
        self.pub64 = self.priv.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint)[1:]
        self.key = None
        self.iv = None

    def hello(self):
        return b"RideOn\x01\x02" + self.pub64

    def accept(self, data):
        if not (data[:6] == b"RideOn" and len(data) == 72):
            return False
        dev64 = data[8:]
        dev_pub = EllipticCurvePublicKey.from_encoded_point(
            SECP256R1(), b"\x04" + dev64)
        secret = self.priv.exchange(ECDH(), dev_pub)
        okm = HKDF(algorithm=hashes.SHA256(), length=36,
                   salt=dev64 + self.pub64, info=b"").derive(secret)
        self.key, self.iv = okm[:32], okm[32:]
        return True

    def decrypt(self, frame):
        nonce = self.iv + frame[:4]
        return AESCCM(self.key, tag_length=4).decrypt(nonce, frame[4:], None)


class ClickV1Driver(DeviceDriver):
    device_type = "zwift_click_v1"
    capabilities = frozenset({"plus_button", "minus_button", "battery"})

    def __init__(self, verbose=lambda: False, status=lambda *args: None,
                 battery=lambda value: None, log=lambda value: None,
                 diagnostic=lambda *args: None, tick=lambda: None):
        self.verbose, self.status = verbose, status
        self.battery, self.log, self.diagnostic = battery, log, diagnostic
        self.tick = tick
        self.crypto = None
        self.ready = False
        self.state = {"plus": False, "minus": False}
        self.emit_event = None
        self.last_battery = None
        self.last_error = None
        self.info = DeviceInfo(self.device_type, "Zwift Click V1", "Zwift",
                               capabilities=self.capabilities)

    def get_device_info(self):
        return self.info

    async def detect(self):
        self.info = replace(self.info, connection_state=ConnectionState.SCANNING)
        try:
            device = await BleakScanner.find_device_by_filter(
                lambda d, ad: bool(d.name) and d.name.startswith(DEVICE_NAME_PREFIX), timeout=30)
        except Exception:
            self.info = replace(self.info, connection_state=ConnectionState.ERROR)
            raise
        if device is None:
            self.info = replace(self.info, connection_state=ConnectionState.DISCONNECTED)
        return device

    async def run(self, device, emit):
        self.emit_event = emit
        self.crypto = ClickCrypto()
        self.ready = False
        self.state = {"plus": False, "minus": False}
        self.info = DeviceInfo(self.device_type, "Zwift Click V1", "Zwift",
                               device.address, capabilities=self.capabilities,
                               connection_state=ConnectionState.CONNECTING)
        self.status("Click trouvé, connexion…", "orange")
        try:
            async with BleakClient(device) as client:
                self.info = DeviceInfo(self.device_type, "Zwift Click V1", "Zwift",
                                       device.address, capabilities=self.capabilities,
                                       connection_state=ConnectionState.CONNECTED)
                self.log(f"Connecté à {device.address}")
                await client.start_notify(ASYNC, self.on_async)
                await client.start_notify(SYNC_TX, self.on_sync_tx)
                await client.write_gatt_char(SYNC_RX, self.crypto.hello(), response=True)
                self.status("Connecté, échange des clés…", "orange")
                waited = 0.0
                while client.is_connected:
                    await asyncio.sleep(0.1)
                    waited += 0.1
                    self.tick()
                    if not self.ready and waited > 15:
                        msg = ("Échange des clés impossible : le Click est peut-être déjà "
                               "connecté à une autre appli, ou son firmware est différent.")
                        self.info = DeviceInfo(self.device_type, "Zwift Click V1", "Zwift",
                                               device.address, capabilities=self.capabilities,
                                               connection_state=ConnectionState.ERROR,
                                               compatibility=CompatibilityStatus.INCOMPATIBLE)
                        self.log(msg)
                        return msg, "red"
        finally:
            self.state = {"plus": False, "minus": False}
            self.info = DeviceInfo(self.device_type, "Zwift Click V1", "Zwift",
                                   device.address, capabilities=self.capabilities,
                                   connection_state=ConnectionState.DISCONNECTED,
                                   compatibility=(CompatibilityStatus.COMPATIBLE if self.ready
                                                  else self.info.compatibility))
        self.log("Click déconnecté")
        return "Click déconnecté : réveille-le (appui sur un bouton)", "orange"

    def on_sync_tx(self, _, data):
        if self.crypto.accept(bytes(data)):
            self.log("Clé de l'appareil reçue")

    def on_async(self, _, data):
        data = bytes(data)
        try:
            if len(data) >= 9:
                if self.crypto.key is None:
                    return
                pt = self.crypto.decrypt(data)
                if not self.ready:
                    self.ready = True
                    self.last_error = None
                    self.info = DeviceInfo(self.device_type, "Zwift Click V1", "Zwift",
                                           self.info.device_id, capabilities=self.capabilities,
                                           connection_state=ConnectionState.CONNECTED,
                                           compatibility=CompatibilityStatus.COMPATIBLE)
                    self.status("Connecté : prêt", "green")
            else:
                pt = data
        except Exception:
            if self.verbose():
                self.log(f"Trame illisible : {data.hex()}")
                self.diagnostic(ASYNC, data.hex(), "", "UNREADABLE", "—")
            return
        self.handle(pt, data)

    def handle(self, pt, wire_payload=None):
        if not pt:
            if self.verbose(): self.log("Notification Click vide ignorée")
            return
        t, fields = pt[0], parse_pb(pt[1:])
        if self.verbose(): self.log(f"type={t:#04x} champs={fields} brut={pt.hex()}")
        if t == BATTERY_TYPE and 2 in fields:
            pct = fields[2]
            if isinstance(pct, int) and 0 <= pct <= 100:
                self.battery(pct)
                if pct != self.last_battery:
                    self.last_battery = pct
            elif self.verbose(): self.log(f"Niveau de batterie invalide ignoré : {pct!r}")
            if self.verbose():
                self.diagnostic(ASYNC, wire_payload.hex() if wire_payload else "",
                               pt.hex(), "BATTERY", "—")
        elif t == CLICK_TYPE:
            now = {"plus": fields.get(1) == 0, "minus": fields.get(2) == 0}
            for which in ("plus", "minus"):
                if now[which] and not self.state[which]:
                    self.state[which] = True
                    kind = EventType.PLUS_DOWN if which == "plus" else EventType.MINUS_DOWN
                    self.emit_event(DeviceEvent(kind, device_id=self.info.device_id),
                                    wire_payload, pt)
                    self.log(f"BUTTON_{which.upper()}")
                elif not now[which] and self.state[which]:
                    kind = EventType.PLUS_UP if which == "plus" else EventType.MINUS_UP
                    self.emit_event(DeviceEvent(kind, device_id=self.info.device_id),
                                    wire_payload, pt)
                    self.state[which] = False
        elif self.verbose():
            self.diagnostic(ASYNC, wire_payload.hex() if wire_payload else "",
                            pt.hex(), f"UNKNOWN_TYPE_{t:#04x}", "—")
