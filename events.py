"""Événements de périphérique et reconnaissance de gestes indépendants du protocole."""
from dataclasses import dataclass
from enum import Enum
import time


class EventType(str, Enum):
    PLUS_DOWN = "PLUS_DOWN"
    PLUS_UP = "PLUS_UP"
    MINUS_DOWN = "MINUS_DOWN"
    MINUS_UP = "MINUS_UP"
    PLUS_SHORT = "PLUS_SHORT"
    MINUS_SHORT = "MINUS_SHORT"
    PLUS_LONG = "PLUS_LONG"
    MINUS_LONG = "MINUS_LONG"
    PLUS_DOUBLE = "PLUS_DOUBLE"
    MINUS_DOUBLE = "MINUS_DOUBLE"
    COMBINATION = "COMBINATION"
    SEQUENCE = "SEQUENCE"


@dataclass(frozen=True)
class DeviceEvent:
    """Un événement brut ou un geste normalisé, horodaté avec une horloge monotone."""

    type: EventType
    timestamp: float = 0.0
    buttons: tuple = ()
    sequence: tuple = ()
    device_id: str = ""

    def __post_init__(self):
        if self.timestamp == 0.0:
            object.__setattr__(self, "timestamp", time.monotonic())


class EventEngine:
    """Transforme les transitions de boutons en gestes, sans dépendance Bluetooth."""

    BUTTONS = {
        EventType.PLUS_DOWN: "plus",
        EventType.PLUS_UP: "plus",
        EventType.MINUS_DOWN: "minus",
        EventType.MINUS_UP: "minus",
    }
    SHORT_EVENTS = {"plus": EventType.PLUS_SHORT, "minus": EventType.MINUS_SHORT}
    LONG_EVENTS = {"plus": EventType.PLUS_LONG, "minus": EventType.MINUS_LONG}
    DOUBLE_EVENTS = {"plus": EventType.PLUS_DOUBLE, "minus": EventType.MINUS_DOUBLE}

    def __init__(self, long_press_ms=500, double_press_ms=300, sequence_ms=1000):
        self.long_press_seconds = long_press_ms / 1000
        self.double_press_seconds = double_press_ms / 1000
        self.sequence_seconds = sequence_ms / 1000
        self.reset()

    def reset(self):
        self.down_since = {}
        self.long_emitted = set()
        self.combination_emitted = False
        self.pending_short = {}
        self.last_gesture = None

    def feed(self, event):
        """Accepte PLUS_DOWN/UP ou MINUS_DOWN/UP et retourne les événements dérivés."""
        if not isinstance(event, DeviceEvent) or event.type not in self.BUTTONS:
            raise ValueError("EventEngine.feed attend un événement de bouton brut")

        output = self.advance(event.timestamp)
        output.append(event)
        button = self.BUTTONS[event.type]
        is_down = event.type in (EventType.PLUS_DOWN, EventType.MINUS_DOWN)

        if is_down:
            if button not in self.down_since:
                self.down_since[button] = event.timestamp
                if len(self.down_since) == 2 and not self.combination_emitted:
                    self.combination_emitted = True
                    output.append(self._gesture(EventType.COMBINATION,
                                                tuple(sorted(self.down_since)), event.timestamp))
            return output

        started = self.down_since.pop(button, None)
        was_long = button in self.long_emitted
        self.long_emitted.discard(button)
        if not self.down_since:
            self.combination_emitted = False
        if started is None:
            return output

        if was_long or event.timestamp - started >= self.long_press_seconds:
            if not was_long:
                output.extend(self._record_gesture(self.LONG_EVENTS[button], (button,), event.timestamp))
            return output

        pending = self.pending_short.get(button)
        if pending is not None and event.timestamp - pending <= self.double_press_seconds:
            del self.pending_short[button]
            output.extend(self._record_gesture(self.DOUBLE_EVENTS[button], (button,), event.timestamp))
        else:
            self.pending_short[button] = event.timestamp
        return output

    def advance(self, now=None):
        """Émet les appuis longs arrivés à seuil et les courts hors fenêtre double."""
        now = time.monotonic() if now is None else now
        output = []
        for button, started in tuple(self.down_since.items()):
            if (button not in self.long_emitted and
                    now - started >= self.long_press_seconds):
                self.long_emitted.add(button)
                output.extend(self._record_gesture(self.LONG_EVENTS[button], (button,), now))
        for button, released in tuple(self.pending_short.items()):
            if now - released >= self.double_press_seconds:
                del self.pending_short[button]
                output.extend(self._record_gesture(self.SHORT_EVENTS[button], (button,), now))
        return output

    def _record_gesture(self, kind, buttons, timestamp):
        event = self._gesture(kind, buttons, timestamp)
        output = [event]
        previous = self.last_gesture
        if previous and timestamp - previous.timestamp <= self.sequence_seconds:
            output.append(self._gesture(EventType.SEQUENCE,
                                        previous.buttons + event.buttons,
                                        timestamp,
                                        (previous.type, event.type)))
        self.last_gesture = event
        return output

    @staticmethod
    def _gesture(kind, buttons, timestamp, sequence=()):
        return DeviceEvent(kind, timestamp, tuple(buttons), tuple(sequence))
