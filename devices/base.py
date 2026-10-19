"""Contrats génériques entre les périphériques et le reste de l'application."""
from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass, field
from enum import Enum
import logging

from bleak import BleakScanner

logger = logging.getLogger("clickbridge")


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    SCANNING = "scanning"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


class CompatibilityStatus(str, Enum):
    UNKNOWN = "unknown"
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class DeviceInfo:
    device_type: str
    model: str
    manufacturer: str = ""
    device_id: str = ""
    firmware_version: str | None = None
    protocol_version: str | None = None
    capabilities: frozenset[str] = field(default_factory=frozenset)
    connection_state: ConnectionState = ConnectionState.DISCONNECTED
    compatibility: CompatibilityStatus = CompatibilityStatus.UNKNOWN


class DeviceDriver(ABC):
    """Un pilote détecte un appareil et publie des événements normalisés."""
    device_type = "unknown"

    def matches(self, device, advertisement):
        """Indique si une annonce BLE appartient à ce pilote."""
        return False

    @abstractmethod
    async def detect(self):
        """Retourne un périphérique découvert ou None après le délai de scan."""

    @abstractmethod
    async def run(self, device, emit):
        """Gère connexion, écoute, déconnexion et transmission normalisée."""

    @abstractmethod
    def get_device_info(self):
        """Retourne le dernier état connu et les capacités du périphérique."""


class DeviceManager:
    """Découvre et maintient plusieurs connexions BLE en parallèle."""
    def __init__(self, drivers):
        self.drivers = tuple(drivers)
        if not self.drivers:
            raise ValueError("DeviceManager nécessite au moins un pilote")

    async def run(self, emit, scan_timeout=5, on_error=None):
        """Scanne en continu et lance chaque pilote compatible une seule fois.

        Le Zwift Ride annonce deux unités BLE distinctes. Les annonces sont
        donc dispatchées à plusieurs pilotes au cours d'un même scan, tandis
        que les connexions déjà ouvertes restent actives.
        """
        active = {}
        last_scan_error = None
        try:
            while True:
                if len(active) == len(self.drivers):
                    await asyncio.wait(tuple(active.values()),
                                       return_when=asyncio.FIRST_COMPLETED)
                else:
                    try:
                        advertisements = await BleakScanner.discover(
                            timeout=scan_timeout, return_adv=True)
                        last_scan_error = None
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        if not active:
                            raise
                        message = str(exc) or exc.__class__.__name__
                        if message != last_scan_error and on_error:
                            on_error(exc)
                        last_scan_error = message
                        # Certaines radios ne peuvent pas balayer pendant une connexion.
                        # Garder les appareils connectés et réessayer sans les interrompre.
                        await asyncio.wait(tuple(active.values()), timeout=1,
                                           return_when=asyncio.FIRST_COMPLETED)
                        advertisements = {}

                    for device, advertisement in advertisements.values():
                        for driver in self.drivers:
                            if driver in active or not driver.matches(device, advertisement):
                                continue
                            # Le marqueur fabricant distingue le Click (0x09) des unités Ride (0x08/0x07).
                            # Le même pilote Ride ne doit pas ouvrir deux côtés simultanément.
                            if (getattr(driver, "device_type", "") == "zwift_ride"
                                    and any(getattr(other, "device_type", "") == "zwift_ride"
                                            for other in active)):
                                continue
                            active[driver] = asyncio.create_task(driver.run(device, emit))
                            break

                for driver, task in tuple(active.items()):
                    if not task.done():
                        continue
                    del active[driver]
                    try:
                        result = task.result()
                        if (isinstance(result, tuple) and len(result) == 2
                                and callable(getattr(driver, "status", None))):
                            driver.status(*result)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        label = getattr(getattr(driver, "info", None), "model",
                                        driver.device_type)
                        logger = getattr(driver, "log", None)
                        status = getattr(driver, "status", None)
                        if logger:
                            logger(f"{label} : erreur Bluetooth : {exc}")
                        if status:
                            status(f"{label} : erreur de connexion, nouvelle tentative…", "red")
                if not active:
                    await asyncio.sleep(0.25)
        finally:
            tasks = tuple(active.values())
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def run_once(self, emit):
        """Alias conservé pour les anciens appelants; le manager reste actif."""
        return await self.run(emit)
