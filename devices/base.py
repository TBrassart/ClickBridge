"""Contrats génériques entre les périphériques et le reste de l'application."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


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
    """Coordonne les pilotes connus sans exposer BLE au moteur d'actions."""
    def __init__(self, drivers):
        self.drivers = tuple(drivers)
        if not self.drivers:
            raise ValueError("DeviceManager nécessite au moins un pilote")

    async def run_once(self, emit):
        for driver in self.drivers:
            device = await driver.detect()
            if device is not None:
                return await driver.run(device, emit)
        return None
