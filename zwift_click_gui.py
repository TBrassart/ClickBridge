"""ClickBridge : Zwift Click V1 (firmware chiffré) -> touches clavier, avec interface."""
import asyncio
import copy
import ctypes
import datetime
import json
import math
import logging
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox, filedialog
from events import DeviceEvent, EventEngine, EventType
from devices import ClickV1Driver, DeviceManager, ZwiftRideDriver
from diagnostics import export_diagnostic_zip
from config_store import (CURRENT_CONFIG_VERSION, ConfigError, backup_config_file,
                          load_config_file, migrate_config_data, restore_config_file,
                          validate_config,
                          save_config_file)
from app_version import APP_VERSION
from updater import RELEASES_PAGE, UpdateError, check_for_update, download_verified_installer
from profiles import ProfileDialog, make_legacy_profile, normalize_profiles, resolve_profile

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont, ImageTk
except ImportError:
    pystray = None
    Image = ImageDraw = ImageFont = ImageTk = None

from pynput.keyboard import Controller, Key

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", "."), "ZwiftClickClavier")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LOG_DIR = os.path.join(CONFIG_DIR, "logs")
HISTORY_FILE = os.path.join(CONFIG_DIR, "history.json")
UPDATE_DIR = os.path.join(CONFIG_DIR, "updates")
DEFAULTS = {
    "plus": "k",
    "minus": "i",
    "hold_ms": 50,            # durée pendant laquelle la touche reste enfoncée
    "repeat": False,          # répétition si le bouton reste enfoncé
    "repeat_delay": 400,      # délai avant la première répétition (ms)
    "repeat_interval": 120,   # intervalle entre deux répétitions (ms)
    "battery_low": 20,        # alerte sous ce pourcentage (0 = désactivée)
    "launch_at_startup": False,
    "start_minimized": False,
}

kb = Controller()
_mutex = None   # garde la référence du mutex d'instance unique
logger = logging.getLogger("clickbridge")
CONFIG_WRITE_BLOCKED = False
CONFIG_LOAD_ERROR = None


def _rounded_points(width, height, radius):
    points = []
    corners = ((radius, radius, 180), (width - radius, radius, 270),
               (width - radius, height - radius, 0),
               (radius, height - radius, 90))
    for cx, cy, start in corners:
        for step in range(7):
            angle = math.radians(start + step * 15)
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return [coordinate for point in points for coordinate in point]


class RoundedCard(tk.Frame):
    """Frame with a rounded color surface, drawn behind its normal Tk children."""

    def __init__(self, master, fill, border=None, radius=18, **kwargs):
        self.fill = fill
        self.border = border or fill
        self.radius = radius
        self.outer = master.cget("bg")
        super().__init__(master, bg=self.outer, bd=0, highlightthickness=0, **kwargs)
        self.surface = tk.Canvas(self, bg=self.outer, bd=0, highlightthickness=0)
        self.surface.place(x=0, y=0, relwidth=1, relheight=1)
        self.surface.bind("<Configure>", self._draw)

    def _draw(self, _event=None):
        self.surface.delete("surface")
        width, height = self.surface.winfo_width(), self.surface.winfo_height()
        if width > 2 and height > 2:
            self.surface.create_polygon(*_rounded_points(width - 1, height - 1, self.radius),
                                        fill=self.fill, outline=self.border, width=1,
                                        tags="surface")


class RoundedChoice(tk.Canvas):
    """Compact rounded drop-down for the device and profile selectors."""

    def __init__(self, master, variable, values, colors, width=176):
        self.variable = variable
        self.values = list(values)
        self.colors = colors
        self._width = width
        self._hover = False
        self._menu = None
        super().__init__(master, width=width, height=34, bg=master.cget("bg"),
                         bd=0, highlightthickness=0, takefocus=True)
        self.bind("<Configure>", self._draw)
        self.bind("<Button-1>", self._open_menu)
        self.bind("<Enter>", self._set_hover)
        self.bind("<Leave>", self._clear_hover)
        self.bind("<KeyPress-Down>", self._move_selection)
        self.bind("<KeyPress-Up>", self._move_selection)
        self.variable.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _draw(self, _event=None):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width < 4 or height < 4:
            return
        border = self.colors["accent"] if self._hover or self.focus_get() == self else self.colors["border"]
        self.create_polygon(*_rounded_points(width - 2, height - 2, 11),
                            fill=self.colors["card2"], outline=border, width=1, tags="field")
        self.create_text(14, height / 2, text=self.variable.get(), anchor="w",
                         fill=self.colors["text"], font=("Segoe UI", 9), tags="value")
        self.create_line(width - 20, height / 2 - 2, width - 15, height / 2 + 3,
                         width - 10, height / 2 - 2, fill=self.colors["muted"],
                         width=1.5, tags="arrow")

    def configure(self, cnf=None, **kwargs):
        values = kwargs.pop("values", None)
        result = super().configure(cnf, **kwargs)
        if values is not None:
            self.values = list(values)
            self._draw()
        return result

    config = configure

    def get(self):
        return self.variable.get()

    def set(self, value):
        self.variable.set(value)

    def _set_hover(self, _event=None):
        self._hover = True
        self._draw()

    def _clear_hover(self, _event=None):
        self._hover = False
        self._draw()

    def _open_menu(self, _event=None):
        self.focus_set()
        self._menu = tk.Menu(self, tearoff=False, bg=self.colors["card2"], fg=self.colors["text"],
                             activebackground=self.colors["accent"],
                             activeforeground=self.colors["bg"], relief="flat", bd=0,
                             font=("Segoe UI", 9))
        for value in self.values:
            self._menu.add_command(label=value, command=lambda item=value: self._select(item))
        if self.values:
            self._menu.tk_popup(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height())
        return "break"

    def _select(self, value):
        self.variable.set(value)
        self.event_generate("<<ComboboxSelected>>")
        self._draw()

    def _move_selection(self, event):
        if not self.values:
            return "break"
        try:
            index = self.values.index(self.variable.get())
        except ValueError:
            index = 0
        direction = 1 if event.keysym == "Down" else -1
        self._select(self.values[(index + direction) % len(self.values)])
        return "break"


class RoundedControl(tk.Canvas):
    """Rounded, low-overhead visual indicator used for device buttons."""

    def __init__(self, master, text, colors, width, height, radius=12, **kwargs):
        self.caption = text
        self.colors = colors
        self.fill = kwargs.pop("bg", colors["card2"])
        self.foreground = kwargs.pop("fg", colors["text"])
        self.font = kwargs.pop("font", ("Segoe UI", 11, "bold"))
        self.radius = radius
        kwargs.pop("state", None)
        super().__init__(master, width=width, height=height, bg=master.cget("bg"),
                         bd=0, highlightthickness=0, **kwargs)
        self.bind("<Configure>", self._draw)
        self._draw()

    def _draw(self, _event=None):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width > 3 and height > 3:
            self.create_polygon(*_rounded_points(width - 2, height - 2, self.radius),
                                fill=self.fill, outline="", tags="button")
            self.create_text(width / 2, height / 2, text=self.caption,
                             fill=self.foreground, font=self.font, tags="caption")

    def configure(self, cnf=None, **kwargs):
        self.fill = kwargs.pop("bg", kwargs.pop("background", self.fill))
        self.foreground = kwargs.pop("fg", kwargs.pop("foreground", self.foreground))
        kwargs.pop("state", None)
        result = super().configure(cnf, **kwargs)
        self._draw()
        return result

    config = configure

RIDE_BUTTON_EVENTS = {
    EventType.RIDE_LEFT_DOWN: ("left", "LEFT", True, "ride_left"),
    EventType.RIDE_LEFT_UP: ("left", "LEFT", False, "ride_left"),
    EventType.RIDE_UP_DOWN: ("left", "UP", True, "ride_up"),
    EventType.RIDE_UP_UP: ("left", "UP", False, "ride_up"),
    EventType.RIDE_RIGHT_DOWN: ("left", "RIGHT", True, "ride_right"),
    EventType.RIDE_RIGHT_UP: ("left", "RIGHT", False, "ride_right"),
    EventType.RIDE_DOWN_DOWN: ("left", "DOWN", True, "ride_down"),
    EventType.RIDE_DOWN_UP: ("left", "DOWN", False, "ride_down"),
    EventType.RIDE_A_DOWN: ("right", "A", True, "ride_a"),
    EventType.RIDE_A_UP: ("right", "A", False, "ride_a"),
    EventType.RIDE_B_DOWN: ("right", "B", True, "ride_b"),
    EventType.RIDE_B_UP: ("right", "B", False, "ride_b"),
    EventType.RIDE_Y_DOWN: ("right", "Y", True, "ride_y"),
    EventType.RIDE_Y_UP: ("right", "Y", False, "ride_y"),
    EventType.RIDE_Z_DOWN: ("right", "Z", True, "ride_z"),
    EventType.RIDE_Z_UP: ("right", "Z", False, "ride_z"),
    EventType.RIDE_SHIFT_UP_L_DOWN: ("left", "SHIFT_UP_L", True, "ride_shift_up_l"),
    EventType.RIDE_SHIFT_UP_L_UP: ("left", "SHIFT_UP_L", False, "ride_shift_up_l"),
    EventType.RIDE_SHIFT_DN_L_DOWN: ("left", "SHIFT_DN_L", True, "ride_shift_dn_l"),
    EventType.RIDE_SHIFT_DN_L_UP: ("left", "SHIFT_DN_L", False, "ride_shift_dn_l"),
    EventType.RIDE_SHIFT_UP_R_DOWN: ("right", "SHIFT_UP_R", True, "ride_shift_up_r"),
    EventType.RIDE_SHIFT_UP_R_UP: ("right", "SHIFT_UP_R", False, "ride_shift_up_r"),
    EventType.RIDE_SHIFT_DN_R_DOWN: ("right", "SHIFT_DN_R", True, "ride_shift_dn_r"),
    EventType.RIDE_SHIFT_DN_R_UP: ("right", "SHIFT_DN_R", False, "ride_shift_dn_r"),
}
RIDE_PROFILE_ACTIONS = {
    event_type: metadata[3]
    for event_type, metadata in RIDE_BUTTON_EVENTS.items()
    if metadata[2]
}


def configure_logging():
    """Configure un fichier quotidien et conserve au plus 14 jours de journaux."""
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        today = datetime.date.today()
        for name in os.listdir(LOG_DIR):
            if not (name.startswith("clickbridge-") and name.endswith(".log")):
                continue
            try:
                log_date = datetime.date.fromisoformat(
                    name[len("clickbridge-"):-len(".log")])
                if (today - log_date).days > 14:
                    os.remove(os.path.join(LOG_DIR, name))
            except (ValueError, OSError):
                continue
        path = os.path.join(LOG_DIR, f"clickbridge-{today.isoformat()}.log")
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S"))
        logger.addHandler(handler)
    except OSError:
        # Des permissions ou un disque indisponible ne doivent pas empêcher le démarrage.
        logger.addHandler(logging.NullHandler())


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def already_running():
    """Vrai si une autre instance de ClickBridge tourne déjà (Windows)."""
    global _mutex
    if os.name != "nt":
        return False
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    _mutex = k32.CreateMutexW(None, False, "Local\\ClickBridge_instance")
    # 183 = ERROR_ALREADY_EXISTS ; 5 = accès refusé (instance lancée avec d'autres droits)
    return ctypes.get_last_error() in (183, 5)


def load_config():
    try:
        cfg, backup = load_config_file(CONFIG_FILE)
        if backup:
            logger.info("Configuration migrated; backup saved to %s", backup)
        result = dict(DEFAULTS)
        result.update(cfg)
        return result
    except FileNotFoundError:
        return {**DEFAULTS, "configVersion": CURRENT_CONFIG_VERSION,
                "profiles": [], "active_profile": "Automatique", "default_profile": "MyWhoosh"}
    except (OSError, json.JSONDecodeError, ConfigError) as exc:
        global CONFIG_WRITE_BLOCKED, CONFIG_LOAD_ERROR
        CONFIG_WRITE_BLOCKED = True
        CONFIG_LOAD_ERROR = str(exc)
        logger.error("Configuration invalide; fichier préservé: %s", exc)
        return {**DEFAULTS, "configVersion": CURRENT_CONFIG_VERSION,
                "profiles": [], "active_profile": "Automatique", "default_profile": "MyWhoosh"}


def set_windows_startup(enabled, minimized=False):
    """Ajoute ou retire l'entrée de démarrage pour l'utilisateur Windows courant."""
    if os.name != "nt":
        raise OSError("Le démarrage automatique est disponible uniquement sous Windows.")
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if not enabled:
            try:
                winreg.DeleteValue(key, "ClickBridge")
            except FileNotFoundError:
                pass
            return
        args = [sys.executable]
        if not getattr(sys, "frozen", False):
            args[0] = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if not os.path.isfile(args[0]):
                args[0] = sys.executable
            args.append(os.path.abspath(__file__))
        if minimized:
            args.append("--minimized")
        winreg.SetValueEx(key, "ClickBridge", 0, winreg.REG_SZ, subprocess.list2cmdline(args))


def windows_startup_enabled():
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_QUERY_VALUE) as key:
            winreg.QueryValueEx(key, "ClickBridge")
        return True
    except OSError:
        return False


def resolve_key(name):
    """'i' -> 'i' ; 'up' / 'space' / 'page_up'... -> touche spéciale pynput."""
    name = (name or "").strip()
    if len(name) == 1:
        return name
    return getattr(Key, name.lower(), None)


def explain(e):
    """Traduit une exception en message compréhensible : (texte, couleur)."""
    msg = str(e) or e.__class__.__name__
    low = msg.lower()
    if isinstance(e, (asyncio.TimeoutError, TimeoutError)) or "timeout" in low or "timed out" in low:
        return ("Le périphérique Zwift n'a pas répondu à temps. Réveille-le et rapproche-le du PC.",
                "orange")
    if "denied" in low:
        return ("Accès Bluetooth refusé : le périphérique est peut-être déjà connecté à "
                "Zwift, Companion, une autre application ou Windows. Ferme cette connexion "
                "puis réessaie.", "red")
    if any(w in low for w in ("adapter", "radio", "not available", "turned off",
                              "powered off", "bluetooth")):
        return ("Bluetooth indisponible : vérifie que le Bluetooth est activé dans "
                "Windows (mode avion désactivé) et qu'un adaptateur est présent.", "red")
    if any(w in low for w in ("disconnect", "not connected", "unreachable")):
        return ("Connexion Bluetooth perdue. Réveille le périphérique et patiente quelques secondes.",
                "orange")
    return (f"Erreur inattendue : {msg}", "red")


class Worker:
    """Boucle Bluetooth, exécutée dans un thread à part."""

    def __init__(self, ui_queue, shared):
        self.q = ui_queue
        self.shared = shared
        self.loop = None
        self.task = None
        self.stop_requested = False
        self.state = {"plus": False, "minus": False}
        self.tasks = set()
        self.last_error = None
        self.not_found = 0
        self.search_logged = False
        self.last_battery = {}
        self.event_engine = EventEngine()
        self.last_profile_name = None
        self.device_states = {
            "click": ("En attente de recherche", "orange"),
            "ride_left": ("En attente de recherche", "orange"),
            "ride_right": ("En attente de recherche", "orange"),
        }
        self.click_driver = ClickV1Driver(
            verbose=lambda: self.shared["verbose"],
            status=lambda text, color: self.on_device_status("click", text, color),
            battery=self.on_battery, log=self.on_driver_log,
            diagnostic=lambda *args: self.emit("diagnostic", *args),
            tick=lambda: self.publish_events(self.event_engine.advance()))
        self.ride_drivers = {
            side: ZwiftRideDriver(
                side,
                verbose=lambda: self.shared["verbose"],
                status=lambda text, color, side=side: self.on_device_status(
                    f"ride_{side}", text, color),
                battery=lambda value, side=side: self.on_ride_battery(side, value),
                log=self.on_driver_log,
                diagnostic=lambda *args: self.emit("diagnostic", *args),
                tick=lambda: self.publish_events(self.event_engine.advance()))
            for side in ("left", "right")
        }
        self.drivers = {"click": self.click_driver,
                        "ride_left": self.ride_drivers["left"],
                        "ride_right": self.ride_drivers["right"]}
        # Compatibilité pour les appels existants ; l'export utilise maintenant tous les pilotes.
        self.driver = self.click_driver
        self.device_manager = DeviceManager(list(self.drivers.values()))

    def emit(self, *msg):
        self.q.put(msg)

    def report(self, msg, detail=None):
        """Écrit un message dans le journal une seule fois tant qu'il ne change pas."""
        if msg != self.last_error:
            self.last_error = msg
            self.emit("log", msg)
            logger.warning("%s%s", msg, f" ({detail})" if detail else "")

    def on_scan_error(self, error):
        message, _color = explain(error)
        self.report(message, repr(error))

    def on_device_status(self, key, text, color):
        self.device_states[key] = (text, color)
        self.emit("device_status", key, text, color)
        if color != "green":
            self.emit("battery" if key == "click" else "device_battery",
                      *(() if key == "click" else (key,)), None)
        connected = [name for name, (_detail, state) in self.device_states.items()
                     if state == "green"]
        if connected:
            labels = {"click": "Click V1", "ride_left": "Ride gauche",
                      "ride_right": "Ride droite"}
            overall, overall_color = "Connecté : " + ", ".join(
                labels.get(name, name) for name in connected), "green"
        elif color == "red" or any(state == "red" for _detail, state in self.device_states.values()):
            overall, overall_color = "Connexion d'un périphérique en erreur", "red"
        else:
            overall, overall_color = "Recherche des périphériques Zwift…", "orange"
        labels = {"click": "Click V1", "ride_left": "Ride gauche",
                  "ride_right": "Ride droite"}
        details = " · ".join(
            f"{labels.get(name, name)} : {detail}"
            for name, (detail, state) in self.device_states.items()
            if state in ("red", "orange"))
        self.emit("status", overall, overall_color)
        self.emit("status_detail", details)

    # ---------- cycle de vie ----------
    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        self.reconnect_event = asyncio.Event()
        self.task = loop.create_task(self.main())
        if self.stop_requested:
            loop.call_soon(self.task.cancel)
        try:
            loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            pass
        finally:
            loop.close()
            self.emit("status", "Arrêté", "gray")
            self.emit("battery", None)
            for key in self.device_states:
                self.emit("device_status", key, "Arrêté", "gray")
                if key.startswith("ride_"):
                    self.emit("device_battery", key, None)

    def stop(self):
        self.stop_requested = True
        if self.loop and self.task and not self.task.done():
            self.loop.call_soon_threadsafe(self.task.cancel)

    def request_reconnect(self):
        event = getattr(self, "reconnect_event", None)
        if self.loop and event is not None and not self.stop_requested:
            self.loop.call_soon_threadsafe(event.set)

    # ---------- Bluetooth ----------
    async def main(self):
        while True:
            session_task = asyncio.create_task(self.session())
            reconnect_task = asyncio.create_task(self.reconnect_event.wait())
            try:
                done, _ = await asyncio.wait((session_task, reconnect_task),
                                             return_when=asyncio.FIRST_COMPLETED)
                if reconnect_task in done and reconnect_task.result():
                    session_task.cancel()
                    await asyncio.gather(session_task, return_exceptions=True)
                    self.reconnect_event.clear()
                    self.emit("status", "Reprise de Windows : nouvelle recherche des périphériques…", "orange")
                    logger.info("Windows resume detected; restarting device discovery")
                    continue
                reconnect_task.cancel()
                await asyncio.gather(reconnect_task, return_exceptions=True)
                msg, color = session_task.result()
            except asyncio.CancelledError:
                session_task.cancel()
                reconnect_task.cancel()
                await asyncio.gather(session_task, reconnect_task, return_exceptions=True)
                raise
            except Exception as e:
                reconnect_task.cancel()
                await asyncio.gather(reconnect_task, return_exceptions=True)
                msg, color = explain(e)
                self.report(msg, repr(e))
                if self.shared["verbose"]:
                    self.emit("log", f"détail technique : {e!r}")
            self.emit("status", msg, color)
            await asyncio.sleep(2)

    async def session(self):
        self.emit("status", "Recherche des périphériques Zwift…", "orange")
        self.emit("battery", None)
        if not self.search_logged:
            logger.info("Searching for Zwift devices")
            self.search_logged = True
        for key in self.device_states:
            self.on_device_status(key, "Recherche Bluetooth…", "orange")
        try:
            await self.device_manager.run(self.on_device_event, on_error=self.on_scan_error)
        finally:
            self.state = {"plus": False, "minus": False}
            for task in list(self.tasks):
                task.cancel()
            self.event_engine.reset()
        return "Recherche des périphériques Zwift…", "orange"

    def on_battery(self, pct):
        self.emit("battery", pct)
        if pct != self.last_battery.get("click"):
            logger.info("Battery: %d%%", pct)
            self.last_battery["click"] = pct

    def on_ride_battery(self, side, pct):
        self.emit("device_battery", f"ride_{side}", pct)
        key = f"ride_{side}"
        if pct != self.last_battery.get(key):
            logger.info("Battery (%s): %d%%", key, pct)
            self.last_battery[key] = pct

    def on_driver_log(self, message):
        self.emit("log", message)
        if (message in ("Clé de l'appareil reçue", "Click déconnecté")
                or message.startswith(("Connecté à ", "Zwift Ride ", "Clé de l'unité"))):
            logger.info(message)

    def on_device_event(self, event, wire_payload=None, decoded_payload=None):
        """Seuls les événements normalisés du pilote entrent dans le moteur de gestes."""
        if event.type in EventEngine.BUTTONS:
            derived = self.event_engine.feed(event)
            self.publish_events(derived, wire_payload=wire_payload,
                                decoded_payload=decoded_payload)
        else:
            self.publish_events([event], wire_payload=wire_payload,
                                decoded_payload=decoded_payload)
        if event.type in (EventType.PLUS_DOWN, EventType.MINUS_DOWN):
            which = "plus" if event.type == EventType.PLUS_DOWN else "minus"
            self.emit("button", which)
            logger.info("BUTTON_%s", which.upper())
        elif event.type in (EventType.PLUS_UP, EventType.MINUS_UP):
            self.emit("ride_release", "plus" if event.type == EventType.PLUS_UP else "minus")
        elif event.type in RIDE_BUTTON_EVENTS:
            side, name, pressed, _action_key = RIDE_BUTTON_EVENTS[event.type]
            self.emit("ride_button", side, name, pressed)
            if pressed:
                logger.info("RIDE_%s_%s", side.upper(), name)
        elif event.type == EventType.RIDE_PADDLE:
            side = "left" if event.device_id.endswith("left") else "right"
            self.emit("ride_paddle", side, event.value)

    def publish_events(self, events, wire_payload=None, decoded_payload=None):
        """Résout chaque événement avec le profil actif puis exécute son action clavier."""
        if not events:
            return
        profile = resolve_profile(self.shared["profiles"], self.shared["active_profile"],
                                  self.shared["default_profile"])
        if profile["name"] != self.last_profile_name:
            self.last_profile_name = profile["name"]
            self.emit("profile", profile["name"])
            logger.info("Active profile: %s", profile["name"])
        actions = profile["actions"]
        for event in events:
            event_name = event.type.value.lower()
            if event.type in RIDE_BUTTON_EVENTS:
                side, name, pressed, _action_key = RIDE_BUTTON_EVENTS[event.type]
                if self.shared["verbose"]:
                    self.emit("diagnostic", "Ride BLE", wire_payload.hex() if wire_payload else "",
                              decoded_payload.hex() if decoded_payload else "",
                              f"{side.upper()}_{name}_{'DOWN' if pressed else 'UP'}", "—")
                if not pressed:
                    continue
            if event.type == EventType.RIDE_PADDLE:
                continue
            if self.shared["verbose"]:
                self.emit("log", f"Événement : {event.type.value}")
            action_key = RIDE_PROFILE_ACTIONS.get(event.type, event_name)
            action = actions.get(action_key, "").strip()
            if self.shared["verbose"]:
                interpreted = ("PLUS" if event.type == EventType.PLUS_DOWN else
                               "MINUS" if event.type == EventType.MINUS_DOWN else event.type.value)
                mapped = f"KEY_{action.upper()}" if action else "—"
                self.emit("diagnostic", "—",
                          wire_payload.hex() if wire_payload is not None else "",
                          decoded_payload.hex() if decoded_payload is not None else "",
                          interpreted, mapped)
            if not action:
                continue
            if event.type in (EventType.PLUS_DOWN, EventType.MINUS_DOWN):
                which = "plus" if event.type == EventType.PLUS_DOWN else "minus"
                label = "+" if which == "plus" else "−"
                self.spawn(self.press_task(which, label, action))
            elif event.type in RIDE_PROFILE_ACTIONS:
                metadata = RIDE_BUTTON_EVENTS[event.type]
                if metadata[2]:
                    label = f"Ride {metadata[0]} — {metadata[1]}"
                    self.spawn(self.send(action_key, label, first=True, key_name=action))
            else:
                which = event.buttons[0] if event.buttons else "plus"
                label = event.type.value
                self.spawn(self.send(which, label, first=True, key_name=action))

    # ---------- envoi des touches ----------
    def spawn(self, coro):
        task = self.loop.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def press_task(self, which, label, key_name):
        """Un appui = une touche ; si le bouton reste enfoncé et que la répétition
        est activée, la touche est renvoyée à intervalle régulier."""
        if not await self.send(which, label, first=True, key_name=key_name):
            return
        if not self.shared["repeat"]:
            return
        await asyncio.sleep(self.shared["repeat_delay"] / 1000)
        while self.state[which] and self.shared["repeat"]:
            if not await self.send(which, label, first=False, key_name=key_name):
                return
            hold = max(10, self.shared["hold_ms"]) / 1000
            await asyncio.sleep(max(0.0, self.shared["repeat_interval"] / 1000 - hold))

    async def send(self, which, label, first, key_name=None):
        name = self.shared[which] if key_name is None else key_name
        key = resolve_key(name)
        if key is None:
            self.emit("log", f"Touche inconnue pour {label} : « {name} »")
            return False
        hold = max(10, self.shared["hold_ms"]) / 1000
        try:
            kb.press(key)
            try:
                await asyncio.sleep(hold)
            finally:
                kb.release(key)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.emit("log", f"Impossible d'envoyer la touche : {e}")
            return False
        if first:
            self.emit("press", f"{label}  →  {name}", which)
            logger.info("Action KEY_%s", name.upper())
        return True


class App:
    COLORS = {"green": "#34d399", "minus": "#8b7cff", "orange": "#fbbf24",
              "gray": "#9fb3d9", "red": "#f87171"}

    def __init__(self, root):
        self.root = root
        root.title("Click Bridge")
        try:
            root.iconbitmap(resource_path("logo.ico"))
        except Exception:
            pass
        cfg = load_config()
        reserved_config_keys = set(DEFAULTS) | {
            "configVersion", "profiles", "active_profile", "default_profile"}
        self.config_extras = {key: value for key, value in cfg.items()
                              if key not in reserved_config_keys}
        self.shared = {k: cfg[k] for k in DEFAULTS}
        self.shared["launch_at_startup"] = windows_startup_enabled()
        self.shared["profiles"] = normalize_profiles(
            cfg.get("profiles"), self.shared["plus"], self.shared["minus"])
        names = {p["name"].casefold() for p in self.shared["profiles"]}
        configured_default = str(cfg.get("default_profile", "MyWhoosh"))
        self.shared["default_profile"] = (configured_default if configured_default.casefold() in names
                                           else self.shared["profiles"][0]["name"])
        configured_active = str(cfg.get("active_profile", "Automatique"))
        self.shared["active_profile"] = (configured_active if configured_active.casefold() == "automatique"
                                          or configured_active.casefold() in names else "Automatique")
        self.shared["verbose"] = False
        self.shared["advanced_capture"] = False
        self.updating_legacy_keys = False
        self.queue = queue.Queue()
        self.worker = None
        self.battery_alerted = False
        self.ride_battery_alerted = {"left": False, "right": False}

        self.colors = {"bg": "#050d1f", "card": "#10244a", "card2": "#12284f",
                       "border": "#22427c", "text": "#f4f8ff", "muted": "#9fb3d9",
                       "accent": "#22c3f2", "blue": "#2b7bff", "green": "#34d399",
                       "purple": "#8b7cff", "orange": "#fbbf24", "gray": "#9fb3d9",
                       "red": "#f87171"}
        root.configure(bg=self.colors["bg"])
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        window_width = min(500, max(390, screen_width - 24))
        window_height = min(740, max(620, screen_height - 60))
        root.geometry(f"{window_width}x{window_height}")
        root.minsize(min(390, window_width), min(640, window_height))
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=self.colors["bg"])
        style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["text"])
        style.configure("TLabelframe", background=self.colors["bg"], foreground=self.colors["text"])
        style.configure("TLabelframe.Label", background=self.colors["bg"], foreground=self.colors["text"])
        style.configure("TCheckbutton", background=self.colors["bg"], foreground=self.colors["text"])
        style.configure("TEntry", fieldbackground=self.colors["card2"], foreground=self.colors["text"],
                        padding=(8, 5), bordercolor=self.colors["border"],
                        lightcolor=self.colors["border"], darkcolor=self.colors["border"])
        style.configure("TSpinbox", fieldbackground=self.colors["card2"], foreground=self.colors["text"],
                        padding=(7, 4), bordercolor=self.colors["border"],
                        lightcolor=self.colors["border"], darkcolor=self.colors["border"])
        style.configure("TCombobox", fieldbackground=self.colors["card2"],
                        background=self.colors["card2"], foreground=self.colors["text"],
                        arrowcolor=self.colors["muted"], padding=(8, 5),
                        bordercolor=self.colors["border"], lightcolor=self.colors["border"],
                        darkcolor=self.colors["border"])
        style.configure("Dark.TCombobox", fieldbackground=self.colors["card2"],
                        background=self.colors["card2"], foreground=self.colors["text"],
                        arrowcolor=self.colors["muted"], padding=(8, 5),
                        bordercolor=self.colors["border"], lightcolor=self.colors["border"],
                        darkcolor=self.colors["border"])
        style.map("TCombobox", fieldbackground=[("readonly", self.colors["card2"])],
                  selectbackground=[("readonly", self.colors["card2"])],
                  selectforeground=[("readonly", self.colors["text"])])
        style.configure("TButton", background=self.colors["card2"], foreground=self.colors["text"],
                        padding=(11, 7), borderwidth=0, focusthickness=0)
        style.map("TButton", background=[("active", self.colors["accent"]),
                                         ("disabled", self.colors["card"])],
                  foreground=[("active", self.colors["bg"])])
        style.configure("TCheckbutton", padding=(3, 4), focuscolor=self.colors["accent"])
        style.map("TCheckbutton", background=[("active", self.colors["card"])])
        style.configure("TLabelframe", bordercolor=self.colors["border"], padding=7)

        self.is_active = False
        self.session_elapsed = 0.0
        self.session_started_at = None
        self.change_counts = {"plus": 0, "minus": 0, "ride": 0}
        self.diagnostic_history = []
        self.last_action_text = "–"
        self.current_profile_name = self.shared["default_profile"]
        self.session_saved = False
        self.history_window = None
        self.tray_icon = None
        self.selected_device = "Zwift Click V1"
        self.device_panel = None
        self.click_button_states = {"plus": False, "minus": False}
        self.ride_button_values = {}
        self.ride_device_statuses = {
            "left": ("Recherche Bluetooth…", "orange"),
            "right": ("Recherche Bluetooth…", "orange"),
        }
        self.ride_battery_values = {"left": None, "right": None}
        self.ride_paddle_values = {"left": None, "right": None}
        self.ride_battery_alerted = {"left": False, "right": False}
        self.current_status_color = "orange"
        self.current_status_text = "Recherche des périphériques Zwift…"
        self.last_poll_at = time.time()

        viewport = tk.Frame(root, bg=self.colors["bg"])
        viewport.pack(fill="both", expand=True)
        main = tk.Frame(viewport, bg=self.colors["bg"], padx=12, pady=8)
        main.pack(fill="both", expand=True)
        header = tk.Frame(main, bg=self.colors["bg"])
        header.pack(fill="x")
        self.header_logo = None
        if ImageTk is not None:
            try:
                with Image.open(resource_path("logo.ico")) as logo_source:
                    logo_image = logo_source.convert("RGBA").resize(
                        (42, 42), Image.Resampling.LANCZOS)
                self.header_logo = ImageTk.PhotoImage(logo_image, master=root)
                tk.Label(header, image=self.header_logo, bg=self.colors["bg"],
                         bd=0).pack(side="left", padx=(0, 10))
            except (OSError, AttributeError, tk.TclError):
                RoundedControl(header, "CB", self.colors, 34, 34, radius=12,
                               bg=self.colors["blue"], fg=self.colors["text"],
                               font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
        else:
            RoundedControl(header, "CB", self.colors, 34, 34, radius=12,
                           bg=self.colors["blue"], fg=self.colors["text"],
                           font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
        brand_text = tk.Frame(header, bg=self.colors["bg"])
        brand_text.pack(side="left")
        tk.Label(brand_text, text="ClickBridge", bg=self.colors["bg"],
                 fg=self.colors["text"], font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(brand_text, text="Zwift Click  →  MyWhoosh", bg=self.colors["bg"],
                 fg=self.colors["muted"], font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 2))

        hero = RoundedCard(main, self.colors["card"], self.colors["border"], padx=12, pady=7)
        hero.pack(fill="x", pady=(8, 8))
        status_row = tk.Frame(hero, bg=self.colors["card"])
        status_row.pack()
        self.status_dot = tk.Label(status_row, text="●", bg=self.colors["card"],
                                   fg=self.colors["orange"], font=("Segoe UI", 17))
        self.status_dot.pack(side="left", padx=(0, 8))
        self.status = tk.Label(status_row, text="RECHERCHE / CONNEXION", bg=self.colors["card"],
                               fg=self.colors["orange"], font=("Segoe UI", 11, "bold"))
        self.status.pack(side="left")
        self.status_detail = tk.Label(hero, text="Recherche des périphériques Zwift…", bg=self.colors["card"],
                                      fg=self.colors["muted"], font=("Segoe UI", 9), wraplength=340)
        self.status_detail.pack(pady=(2, 4))
        selector_row = tk.Frame(hero, bg=self.colors["card"])
        selector_row.pack(fill="x", pady=(4, 0))
        tk.Label(selector_row, text="Équipement", bg=self.colors["card"],
                 fg=self.colors["muted"], font=("Segoe UI", 9)).pack(side="left")
        self.device_selector_var = tk.StringVar(value=self.selected_device)
        self.device_selector = RoundedChoice(
            selector_row, self.device_selector_var,
            ("Zwift Click V1", "Zwift Ride"), self.colors, width=178)
        self.device_selector.pack(side="right")
        self.device_selector.bind("<<ComboboxSelected>>", self.select_device)

        self.device_panel = tk.Frame(hero, bg=self.colors["card"])
        self.device_panel.pack(fill="x", pady=(7, 0))
        self.click_panel = tk.Frame(self.device_panel, bg=self.colors["card"])
        tk.Label(self.click_panel, text="Zwift Click V1", bg=self.colors["card"],
                 fg=self.colors["text"], font=("Segoe UI", 14, "bold")).pack(pady=(2, 1))
        self.click_device_status = tk.Label(self.click_panel, text="Recherche Bluetooth…",
                                            bg=self.colors["card"], fg=self.colors["muted"],
                                            font=("Segoe UI", 9))
        self.click_device_status.pack()
        self.battery = tk.Label(self.click_panel, text="Batterie Click : –",
                                bg=self.colors["card"], fg=self.colors["muted"],
                                font=("Segoe UI", 10))
        self.battery.pack()
        click_buttons = tk.Frame(self.click_panel, bg=self.colors["card"])
        click_buttons.pack(pady=(8, 6))
        self.plus_button = RoundedControl(click_buttons, "+", self.colors, 104, 74,
                                          radius=14, bg=self.colors["card2"],
                                          fg=self.colors["green"],
                                          font=("Segoe UI", 19, "bold"), state="disabled")
        self.plus_button.pack(side="left", padx=18)
        self.minus_button = RoundedControl(click_buttons, "−", self.colors, 104, 74,
                                           radius=14, bg=self.colors["card2"],
                                           fg=self.colors["purple"],
                                           font=("Segoe UI", 19, "bold"), state="disabled")
        self.minus_button.pack(side="left", padx=18)
        self.last = tk.Label(self.click_panel, text="Dernière action : –",
                             bg=self.colors["card"], fg=self.colors["muted"],
                             font=("Segoe UI", 10))
        self.last.pack()

        self.ride_panel = tk.Frame(self.device_panel, bg=self.colors["card"])
        self.ride_title = tk.Label(self.ride_panel, text="Zwift Ride",
                                   bg=self.colors["card"], fg=self.colors["text"],
                                   font=("Segoe UI", 14, "bold"))
        self.ride_title.pack(pady=(2, 1))
        tk.Label(self.ride_panel,
                 text="Intégration expérimentale — protocole observé sur firmware 1.1.0",
                 bg=self.colors["card"], fg=self.colors["muted"],
                 font=("Segoe UI", 8), wraplength=390, justify="center").pack()
        ride_sides = tk.Frame(self.ride_panel, bg=self.colors["card"])
        ride_sides.pack(fill="x", pady=(2, 0))
        self.ride_side_panels = {}
        self.ride_button_frames = {}
        self.ride_device_status_labels = {}
        self.ride_battery_labels = {}
        self.ride_paddle_labels = {}
        self.ride_button_labels = {}
        self.ride_device_statuses = {
            "left": ("Recherche Bluetooth…", "orange"),
            "right": ("Recherche Bluetooth…", "orange"),
        }
        self.ride_battery_values = {"left": None, "right": None}
        self.ride_paddle_values = {"left": None, "right": None}
        self.ride_button_values = {}
        self.click_button_states = {"plus": False, "minus": False}
        self.ride_battery_alerted = {"left": False, "right": False}
        for column, side in enumerate(("left", "right")):
            side_panel = RoundedCard(ride_sides, self.colors["card2"], self.colors["border"],
                                     radius=13, padx=6, pady=3)
            side_panel.grid(row=0, column=column, sticky="nsew",
                            padx=(0, 4) if column == 0 else (4, 0))
            ride_sides.columnconfigure(column, weight=1)
            self.ride_side_panels[side] = side_panel
            side_name = "Gauche" if side == "left" else "Droite"
            tk.Label(side_panel, text=side_name, bg=self.colors["card2"],
                     fg=self.colors["text"], font=("Segoe UI", 10, "bold")).pack()
            self.ride_device_status_labels[side] = tk.Label(
                side_panel, text="Recherche Bluetooth…", bg=self.colors["card2"],
                fg=self.colors["muted"], font=("Segoe UI", 8), wraplength=180)
            self.ride_device_status_labels[side].pack()
            self.ride_battery_labels[side] = tk.Label(
                side_panel, text="Batterie : –", bg=self.colors["card2"],
                fg=self.colors["muted"], font=("Segoe UI", 9))
            self.ride_battery_labels[side].pack()
            self.ride_paddle_labels[side] = tk.Label(
                side_panel, text="Paddle : –", bg=self.colors["card2"],
                fg=self.colors["muted"], font=("Segoe UI", 8))
            self.ride_paddle_labels[side].pack()
            button_frame = tk.Frame(side_panel, bg=self.colors["card2"])
            button_frame.pack(pady=(2, 0))
            self.ride_button_frames[side] = button_frame
            self.ride_button_labels[side] = {}
            self.render_ride_buttons(side)
        self.click_panel.pack(fill="x")

        profile_card = RoundedCard(main, self.colors["card"], self.colors["border"],
                                   padx=10, pady=6)
        profile_card.pack(fill="x", pady=(0, 7))
        profile_head = tk.Frame(profile_card, bg=self.colors["card"])
        profile_head.pack(fill="x")
        tk.Label(profile_head, text="Profil actif", bg=self.colors["card"], fg=self.colors["muted"],
                 font=("Segoe UI", 9)).pack(side="left")
        self.active_profile_var = tk.StringVar(value=self.shared["active_profile"])
        self.active_profile_combo = RoundedChoice(
            profile_head, self.active_profile_var, [], self.colors, width=168)
        self.active_profile_combo.pack(side="right")
        self.active_profile_combo.bind("<<ComboboxSelected>>", self.active_profile_changed)
        default_row = tk.Frame(profile_card, bg=self.colors["card"])
        default_row.pack(fill="x", pady=(3, 0))
        tk.Label(default_row, text="Par défaut", bg=self.colors["card"], fg=self.colors["muted"],
                 font=("Segoe UI", 9)).pack(side="left")
        self.default_profile_var = tk.StringVar(value=self.shared["default_profile"])
        self.default_profile_combo = RoundedChoice(
            default_row, self.default_profile_var, [], self.colors, width=168)
        self.default_profile_combo.pack(side="right")
        self.default_profile_combo.bind("<<ComboboxSelected>>", self.default_profile_changed)
        self.profile_status = tk.Label(profile_card, text="Profil par défaut", bg=self.colors["card"],
                                       fg=self.colors["muted"], font=("Segoe UI", 8))
        self.profile_status.pack(anchor="w", pady=(2, 0))
        tk.Button(profile_card, text="Gérer les profils", command=self.manage_profiles,
                  relief="flat", bg=self.colors["card"], fg=self.colors["accent"],
                  activebackground=self.colors["card"], activeforeground=self.colors["text"],
                  font=("Segoe UI", 9, "underline")).pack(anchor="w", pady=(1, 0))
        self.refresh_profile_controls()
        self.active_profile_changed()

        stats = RoundedCard(main, self.colors["card"], self.colors["border"],
                            padx=12, pady=8)
        stats.pack(fill="x")
        stats_header = tk.Frame(stats, bg=self.colors["card"])
        stats_header.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 3))
        tk.Label(stats_header, text="Session", bg=self.colors["card"], fg=self.colors["text"],
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Button(stats_header, text="Historique", command=self.open_history, relief="flat",
                  bg=self.colors["card"], fg=self.colors["accent"], activebackground=self.colors["card"],
                  font=("Segoe UI", 9, "underline")).pack(side="right")
        self.stat_values = {}
        stat_rows = (("duration", "Durée", 1, 0), ("changes", "Changements", 1, 2),
                     ("plus", "+ Click", 2, 0), ("minus", "− Click", 2, 2),
                     ("ride", "Appuis Ride", 3, 0),
                     ("average", "Moyenne", 3, 2))
        for key, label, row, column in stat_rows:
            tk.Label(stats, text=label, bg=self.colors["card"], fg=self.colors["muted"],
                     font=("Segoe UI", 9)).grid(row=row, column=column, sticky="w", pady=1)
            value = tk.Label(stats, text="–", bg=self.colors["card"], fg=self.colors["text"],
                             font=("Segoe UI", 9, "bold"))
            value.grid(row=row, column=column + 1, sticky="e", padx=(8, 10), pady=1)
            self.stat_values[key] = value
        stats.columnconfigure(1, weight=1)
        stats.columnconfigure(3, weight=1)

        footer = tk.Frame(main, bg=self.colors["bg"])
        footer.pack(fill="x", pady=(7, 0))
        self.make_button(footer, "Configuration", self.open_configuration).pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.make_button(footer, "Journal", self.open_journal).pack(side="left", expand=True, fill="x", padx=(4, 0))

        # Les réglages détaillés restent accessibles sans encombrer l'écran principal.
        self.config_window = tk.Toplevel(root)
        self.config_window.withdraw()
        self.config_window.title("Click Bridge — Configuration")
        self.config_window.configure(bg=self.colors["bg"])
        config_body = ttk.Frame(self.config_window, padding=12)
        config_body.pack(fill="both", expand=True)
        config_width = min(540, max(390, screen_width - 24))
        config_height = min(740, max(620, screen_height - 60))
        self.config_window.geometry(f"{config_width}x{config_height}")
        self.config_window.minsize(min(390, config_width), min(620, config_height))
        self.config_window.protocol("WM_DELETE_WINDOW", self.config_window.withdraw)
        diagnostics = ttk.LabelFrame(config_body, text="Diagnostic avancé")
        diagnostics.pack(fill="x", pady=(0, 5))
        self.verbose_var = tk.BooleanVar(value=self.shared["advanced_capture"])
        ttk.Checkbutton(
            diagnostics,
            text="Capture protocole avancée (session uniquement)",
            variable=self.verbose_var,
            command=self.set_advanced_capture
        ).pack(anchor="w", padx=8, pady=4)
        ttk.Label(diagnostics, text=("Désactivé par défaut. Peut inclure des trames Bluetooth "
                                     "brutes dans le journal et l'export."),
                  wraplength=max(250, config_width - 60)).pack(anchor="w", padx=8, pady=(0, 5))
        ttk.Button(diagnostics, text="Exporter le diagnostic…",
                   command=self.open_diagnostic_export).pack(anchor="e", padx=8, pady=(0, 6))
        config_actions = ttk.Frame(config_body)
        config_actions.pack(fill="x", pady=(0, 5))
        config_actions.columnconfigure(0, weight=1)
        config_actions.columnconfigure(1, weight=1)
        ttk.Button(config_actions, text="Exporter configuration…",
                   command=self.export_configuration).grid(row=0, column=0, sticky="ew", padx=3, pady=2)
        ttk.Button(config_actions, text="Importer configuration…",
                   command=self.import_configuration).grid(row=0, column=1, sticky="ew", padx=3, pady=2)
        ttk.Button(config_actions, text="Restaurer sauvegarde…",
                   command=self.restore_configuration).grid(row=1, column=0, columnspan=2,
                                                            sticky="ew", padx=3, pady=2)
        ttk.Button(config_actions, text="Restaurer les paramètres par défaut…",
                   command=self.reset_configuration).grid(row=2, column=0, columnspan=2,
                                                          sticky="ew", padx=3, pady=2)

        windows_options = ttk.LabelFrame(config_body, text="Windows")
        windows_options.pack(fill="x", pady=(0, 5))
        self.autostart_var = tk.BooleanVar(value=windows_startup_enabled())
        self.start_minimized_var = tk.BooleanVar(value=self.shared["start_minimized"])
        self.autostart_check = ttk.Checkbutton(
            windows_options, text="Lancer au démarrage de Windows",
            variable=self.autostart_var, command=self.set_autostart)
        self.autostart_check.pack(anchor="w", padx=8, pady=3)
        self.minimized_check = ttk.Checkbutton(
            windows_options, text="Démarrer minimisé dans la zone de notification",
            variable=self.start_minimized_var, command=self.set_start_minimized)
        self.minimized_check.pack(anchor="w", padx=8, pady=(0, 4))
        if os.name != "nt":
            self.autostart_check.state(["disabled"])
            self.minimized_check.state(["disabled"])
        elif pystray is None:
            self.minimized_check.state(["disabled"])

        update_options = ttk.LabelFrame(config_body, text="Mise à jour")
        update_options.pack(fill="x", pady=(0, 5))
        ttk.Label(update_options, text=f"Version actuelle : v{APP_VERSION}").pack(
            side="left" if config_width >= 480 else "top", anchor="w", padx=8, pady=6)
        self.update_button = ttk.Button(update_options, text="Vérifier les mises à jour",
                                        command=self.check_for_updates)
        self.update_button.pack(side="right" if config_width >= 480 else "top",
                                anchor="e", padx=8, pady=6)

        # --- touches du profil par défaut ---
        keys = ttk.LabelFrame(config_body, text="Touches immédiates du profil par défaut")
        keys.pack(fill="x", pady=6)
        self.plus_var = tk.StringVar(value=self.shared["plus"])
        self.minus_var = tk.StringVar(value=self.shared["minus"])
        ttk.Label(keys, text="Bouton +").grid(row=0, column=0, padx=8, pady=6, sticky="w")
        ttk.Entry(keys, textvariable=self.plus_var, width=10).grid(row=0, column=1, padx=4)
        ttk.Label(keys, text="Bouton −").grid(row=0, column=2, padx=(20, 8), sticky="w")
        ttk.Entry(keys, textvariable=self.minus_var, width=10).grid(row=0, column=3, padx=4)
        self.plus_var.trace_add("write", lambda *a: self.legacy_key_changed("plus", self.plus_var.get()))
        self.minus_var.trace_add("write", lambda *a: self.legacy_key_changed("minus", self.minus_var.get()))

        # --- réglages ---
        opts = ttk.LabelFrame(config_body, text="Réglages")
        opts.pack(fill="x", padx=10, pady=4)
        opts.columnconfigure(0, weight=1)
        self.hold_var = tk.IntVar(value=self.shared["hold_ms"])
        self.delay_var = tk.IntVar(value=self.shared["repeat_delay"])
        self.interval_var = tk.IntVar(value=self.shared["repeat_interval"])
        self.battlow_var = tk.IntVar(value=self.shared["battery_low"])
        self.repeat_var = tk.BooleanVar(value=self.shared["repeat"])
        self.add_spin(opts, 0, "Durée d'appui de la touche", self.hold_var, 10, 500, 10, "ms", "hold_ms")
        ttk.Checkbutton(opts, text="Répéter la touche si le bouton reste enfoncé",
                        variable=self.repeat_var,
                        command=lambda: self.shared.__setitem__("repeat", self.repeat_var.get())
                        ).grid(row=1, column=0, columnspan=3, padx=8, pady=2, sticky="w")
        self.add_spin(opts, 2, "Délai avant la première répétition", self.delay_var, 100, 3000, 50, "ms", "repeat_delay")
        self.add_spin(opts, 3, "Intervalle entre répétitions", self.interval_var, 30, 1000, 10, "ms", "repeat_interval")
        self.add_spin(opts, 4, "Alerte batterie sous (0 = aucune)", self.battlow_var, 0, 50, 5, "%", "battery_low")

        # --- commandes et journal ---
        bar = ttk.Frame(config_body)
        bar.pack(fill="x", pady=6)
        self.toggle = ttk.Button(bar, text="Arrêter", command=self.toggle_worker)
        self.toggle.pack(side="left")

        self.journal_window = tk.Toplevel(root)
        self.journal_window.withdraw()
        self.journal_window.title("Click Bridge — Journal")
        journal_body = tk.Frame(self.journal_window, bg=self.colors["bg"], padx=12, pady=12)
        journal_body.pack(fill="both", expand=True)
        self.log = tk.Text(journal_body, height=22, state="disabled", wrap="word",
                           bg=self.colors["card"], fg=self.colors["text"],
                           insertbackground=self.colors["text"], relief="flat",
                           font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)
        self.make_button(journal_body, "Copier le journal", self.copy_journal).pack(anchor="e", pady=(8, 0))
        self.journal_window.geometry(
            f"{min(560, max(390, screen_width - 24))}x{min(420, max(320, screen_height - 80))}")
        self.journal_window.protocol("WM_DELETE_WINDOW", self.journal_window.withdraw)

        root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.start_worker()
        self.poll()
        self.start_tray()
        if CONFIG_LOAD_ERROR:
            root.after(0, lambda: messagebox.showwarning(
                "Configuration invalide",
                "Le fichier de configuration contient une erreur et a été conservé sans modification. "
                "Les réglages par défaut sont utilisés temporairement. Corrigez ou restaurez une "
                "sauvegarde depuis Configuration.\n\n" + CONFIG_LOAD_ERROR, parent=root))
        if ("--minimized" in sys.argv and self.shared["start_minimized"]
                and self.tray_icon is not None):
            root.withdraw()

    def add_spin(self, parent, row, label, var, lo, hi, step, unit, key):
        ttk.Label(parent, text=label).grid(row=row, column=0, padx=8, pady=3, sticky="w")
        ttk.Spinbox(parent, from_=lo, to=hi, increment=step, textvariable=var,
                    width=6).grid(row=row, column=1, padx=4)
        ttk.Label(parent, text=unit).grid(row=row, column=2, padx=(0, 8), sticky="w")

        def changed(*_):
            try:
                self.shared[key] = max(lo, min(hi, int(var.get())))
            except (tk.TclError, ValueError):
                pass        # champ vide ou invalide : on garde la valeur précédente
        var.trace_add("write", changed)

    def refresh_profile_controls(self):
        profiles = self.shared["profiles"]
        names = [profile["name"] for profile in profiles]
        self.active_profile_combo.configure(values=["Automatique"] + names)
        self.default_profile_combo.configure(values=names)
        self.active_profile_var.set(self.shared["active_profile"])
        self.default_profile_var.set(self.shared["default_profile"])
        self.update_tray_menu()

    def active_profile_changed(self, _event=None):
        self.shared["active_profile"] = self.active_profile_var.get()
        profile = resolve_profile(self.shared["profiles"], self.shared["active_profile"],
                                  self.shared["default_profile"])
        self.current_profile_name = profile["name"]
        self.profile_status.config(text=f"Profil effectif : {profile['name']}")
        self.update_tray_menu()

    def default_profile_changed(self, _event=None):
        self.shared["default_profile"] = self.default_profile_var.get()
        self.update_legacy_entries()
        self.active_profile_changed()
        self.update_tray_menu()

    def manage_profiles(self):
        ProfileDialog(self.root, self.shared["profiles"], self.profiles_changed)

    def profiles_changed(self, profiles):
        self.shared["profiles"] = normalize_profiles(profiles)
        names = {profile["name"].casefold(): profile["name"]
                 for profile in self.shared["profiles"]}
        if self.shared["default_profile"].casefold() not in names:
            self.shared["default_profile"] = self.shared["profiles"][0]["name"]
        else:
            self.shared["default_profile"] = names[self.shared["default_profile"].casefold()]
        active = self.shared["active_profile"]
        if active.casefold() != "automatique":
            self.shared["active_profile"] = names.get(active.casefold(), "Automatique")
        self.refresh_profile_controls()
        self.update_legacy_entries()
        self.active_profile_changed()

    def legacy_key_changed(self, which, value):
        self.shared[which] = value
        if self.updating_legacy_keys:
            return
        default_name = self.shared["default_profile"].casefold()
        action_name = f"{which}_down"
        for profile in self.shared["profiles"]:
            if profile["name"].casefold() == default_name:
                profile["actions"][action_name] = value
                break

    def update_legacy_entries(self):
        if not hasattr(self, "plus_var") or not hasattr(self, "minus_var"):
            return
        default_name = self.shared["default_profile"].casefold()
        profile = next((p for p in self.shared["profiles"]
                        if p["name"].casefold() == default_name), None)
        if not profile:
            return
        plus, minus = (profile["actions"].get("plus_down", self.shared["plus"]),
                       profile["actions"].get("minus_down", self.shared["minus"]))
        self.updating_legacy_keys = True
        try:
            self.shared["plus"], self.shared["minus"] = plus, minus
            self.plus_var.set(plus)
            self.minus_var.set(minus)
        finally:
            self.updating_legacy_keys = False

    def save_config(self):
        if CONFIG_WRITE_BLOCKED:
            return False
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            save_config_file(CONFIG_FILE, self.config_snapshot())
            return True
        except (OSError, ConfigError, TypeError, ValueError) as exc:
            logger.error("Configuration non enregistrée: %s", exc)
            return False

    def config_snapshot(self):
        config = copy.deepcopy(self.config_extras)
        config.update({key: self.shared[key] for key in DEFAULTS})
        config.update({"profiles": self.shared["profiles"],
                       "active_profile": self.shared["active_profile"],
                       "default_profile": self.shared["default_profile"],
                       "configVersion": CURRENT_CONFIG_VERSION})
        return config

    def export_configuration(self):
        path = filedialog.asksaveasfilename(
            parent=self.config_window, title="Exporter la configuration",
            initialfile="clickbridge-config.json", defaultextension=".json",
            filetypes=(("Fichier JSON", "*.json"), ("Tous les fichiers", "*.*")))
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.config_snapshot(), fh, ensure_ascii=False, indent=2)
            messagebox.showinfo("Configuration exportée", "La configuration a été exportée.",
                                parent=self.config_window)
        except OSError as exc:
            messagebox.showerror("Export impossible", str(exc), parent=self.config_window)

    def set_advanced_capture(self):
        enabled = bool(self.verbose_var.get())
        self.shared["advanced_capture"] = enabled
        self.shared["verbose"] = enabled
        logger.info("Advanced protocol capture %s", "enabled" if enabled else "disabled")

    def set_autostart(self):
        enabled = bool(self.autostart_var.get())
        try:
            set_windows_startup(enabled, bool(self.start_minimized_var.get()))
        except OSError as exc:
            self.autostart_var.set(not enabled)
            messagebox.showerror("Démarrage automatique impossible", str(exc),
                                 parent=self.config_window)
            return
        self.shared["launch_at_startup"] = enabled
        self.save_config()

    def set_start_minimized(self):
        enabled = bool(self.start_minimized_var.get())
        self.shared["start_minimized"] = enabled
        if self.autostart_var.get():
            try:
                set_windows_startup(True, enabled)
            except OSError as exc:
                self.start_minimized_var.set(not enabled)
                self.shared["start_minimized"] = not enabled
                messagebox.showerror("Option Windows impossible", str(exc),
                                     parent=self.config_window)
                return
        self.save_config()

    def apply_configuration(self, config):
        """Applique un objet validé sans perdre les options déjà présentes."""
        reserved = set(DEFAULTS) | {"configVersion", "profiles", "active_profile", "default_profile"}
        self.config_extras = {key: copy.deepcopy(value) for key, value in config.items()
                              if key not in reserved}
        self.shared.update({key: config.get(key, DEFAULTS[key]) for key in DEFAULTS})
        self.shared["profiles"] = normalize_profiles(
            config.get("profiles"), self.shared["plus"], self.shared["minus"])
        names = {profile["name"].casefold(): profile["name"]
                 for profile in self.shared["profiles"]}
        self.shared["default_profile"] = names.get(
            str(config.get("default_profile", self.shared["profiles"][0]["name"])).casefold(),
            self.shared["profiles"][0]["name"])
        active = str(config.get("active_profile", "Automatique"))
        self.shared["active_profile"] = (
            "Automatique" if active.casefold() == "automatique"
            else names.get(active.casefold(), "Automatique"))
        self.refresh_profile_controls()
        self.update_legacy_entries()
        self.active_profile_changed()
        self.hold_var.set(self.shared["hold_ms"])
        self.delay_var.set(self.shared["repeat_delay"])
        self.interval_var.set(self.shared["repeat_interval"])
        self.battlow_var.set(self.shared["battery_low"])
        self.repeat_var.set(self.shared["repeat"])
        self.autostart_var.set(self.shared["launch_at_startup"])
        self.start_minimized_var.set(self.shared["start_minimized"])
        self.save_config()
        if os.name == "nt":
            try:
                set_windows_startup(self.shared["launch_at_startup"],
                                    self.shared["start_minimized"])
            except OSError as exc:
                messagebox.showwarning("Option Windows non appliquée", str(exc),
                                       parent=self.config_window)

    def restore_configuration(self):
        backup_dir = os.path.join(CONFIG_DIR, "backups")
        path = filedialog.askopenfilename(
            parent=self.config_window, title="Restaurer une sauvegarde",
            initialdir=backup_dir if os.path.isdir(backup_dir) else CONFIG_DIR,
            filetypes=(("Configuration JSON", "*.json"), ("Tous les fichiers", "*.*")))
        if not path:
            return
        global CONFIG_WRITE_BLOCKED, CONFIG_LOAD_ERROR
        try:
            config = restore_config_file(CONFIG_FILE, path)
            CONFIG_WRITE_BLOCKED = False
            CONFIG_LOAD_ERROR = None
            config = {**DEFAULTS, **config}
            self.apply_configuration(config)
            messagebox.showinfo("Configuration restaurée",
                                "La sauvegarde a été validée et restaurée. "
                                "La configuration précédente a aussi été sauvegardée.",
                                parent=self.config_window)
        except (OSError, json.JSONDecodeError, ConfigError, ValueError) as exc:
            messagebox.showerror("Restauration impossible", str(exc),
                                 parent=self.config_window)

    def reset_configuration(self):
        confirmed = messagebox.askyesno(
            "Restaurer les paramètres par défaut",
            "Cette opération réinitialisera les paramètres de ClickBridge. "
            "Une sauvegarde sera créée automatiquement. Continuer ?",
            icon="warning", default=messagebox.NO, parent=self.config_window)
        if not confirmed:
            return
        global CONFIG_WRITE_BLOCKED, CONFIG_LOAD_ERROR
        try:
            backup = backup_config_file(CONFIG_FILE, "pre-reset")
            profile = make_legacy_profile(DEFAULTS["plus"], DEFAULTS["minus"])
            defaults = {**DEFAULTS, "profiles": [profile],
                        "active_profile": "Automatique", "default_profile": profile["name"],
                        "configVersion": CURRENT_CONFIG_VERSION}
            # Écrire les valeurs d'usine avant de les appliquer à l'interface.
            save_config_file(CONFIG_FILE, defaults)
            CONFIG_WRITE_BLOCKED = False
            CONFIG_LOAD_ERROR = None
            self.apply_configuration(defaults)
            self.shared["advanced_capture"] = False
            self.shared["verbose"] = False
            self.verbose_var.set(False)
            backup_message = (f"Sauvegarde créée :\n{backup}" if backup else
                              "Aucun ancien fichier de configuration à sauvegarder.")
            messagebox.showinfo("Paramètres restaurés",
                                "Les paramètres par défaut sont actifs.\n\n" + backup_message,
                                parent=self.config_window)
        except (OSError, ConfigError, TypeError, ValueError) as exc:
            messagebox.showerror("Réinitialisation impossible", str(exc),
                                 parent=self.config_window)

    def check_for_updates(self):
        self.update_button.state(["disabled"])
        self.update_button.configure(text="Vérification…")
        threading.Thread(target=self._check_for_updates, daemon=True).start()

    def _check_for_updates(self):
        try:
            result = check_for_update(APP_VERSION)
            self.queue.put(("update_check", result))
        except Exception as exc:
            self.queue.put(("update_check_error", str(exc)))

    def show_update_result(self, update):
        if update["status"] == "no_release":
            messagebox.showinfo(
                "Mises à jour", "Aucune release n’a encore été publiée sur GitHub. "
                f"ClickBridge reste en v{APP_VERSION}.", parent=self.config_window)
            return
        if update["status"] == "current":
            messagebox.showinfo("Mises à jour", f"ClickBridge v{APP_VERSION} est à jour.",
                                parent=self.config_window)
            return
        if not update.get("installer") or not update.get("checksums"):
            if messagebox.askyesno(
                    "Release trouvée",
                    f"La version v{update['latest_version']} est publiée, mais son installateur "
                    "ou son fichier SHA256SUMS est absent. Ouvrir la page GitHub ?",
                    default=messagebox.NO, parent=self.config_window):
                webbrowser.open(update.get("release_url", RELEASES_PAGE))
            return
        notes = update.get("release_notes", "").strip()
        prompt = (f"La version v{update['latest_version']} est disponible.\n\n"
                  "Télécharger et vérifier son installateur ?")
        if notes:
            prompt += "\n\nNotes :\n" + notes[:1800]
        if messagebox.askyesno("Mise à jour disponible", prompt,
                               default=messagebox.NO, parent=self.config_window):
            self.update_button.configure(text="Téléchargement…")
            threading.Thread(target=self._download_update, args=(update,), daemon=True).start()

    def _download_update(self, update):
        try:
            path = download_verified_installer(update, UPDATE_DIR)
            self.queue.put(("update_download", path, update["latest_version"], None))
        except Exception as exc:
            self.queue.put(("update_download", None, update.get("latest_version", ""), str(exc)))

    def finish_update_download(self, path, version, error):
        self.update_button.state(["!disabled"])
        self.update_button.configure(text="Vérifier les mises à jour")
        if error:
            messagebox.showerror("Mise à jour non vérifiée", error,
                                 parent=self.config_window)
            return
        if not messagebox.askyesno(
                "Installateur vérifié",
                f"L’installateur v{version} a été téléchargé et son SHA-256 vérifié. "
                "Lancer l’installation et redémarrer ClickBridge ?",
                default=messagebox.NO, parent=self.config_window):
            return
        try:
            if os.name == "nt":
                # The installer restarts ClickBridge after the current one-file
                # PyInstaller process exits. Do not let it reuse the deleted _MEI dir.
                os.environ.pop("_MEIPASS2", None)
                os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
                shell_execute = ctypes.windll.shell32.ShellExecuteW
                shell_execute.restype = ctypes.c_void_p
                result = shell_execute(
                    None, "runas", path, "/RESTARTAPP", os.path.dirname(path), 1)
                if not result or result <= 32:
                    raise OSError(f"Windows n’a pas pu démarrer l’installateur (code {result}).")
            else:
                subprocess.Popen([path, "/RESTARTAPP"], cwd=os.path.dirname(path),
                                 close_fds=True)
        except PermissionError:
            return
        except OSError as exc:
            messagebox.showerror("Lancement impossible", str(exc), parent=self.config_window)
            return
        self.on_close()

    def open_diagnostic_export(self):
        dialog = tk.Toplevel(self.config_window)
        dialog.title("Exporter le diagnostic")
        dialog.configure(bg=self.colors["bg"])
        dialog.transient(self.config_window)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Données incluses dans l’archive").pack(anchor="w", pady=(0, 8))
        anonymize_var = tk.BooleanVar(value=True)
        configuration_var = tk.BooleanVar(value=False)
        capture_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="Anonymiser les adresses Bluetooth, chemins Windows et noms de profils",
                        variable=anonymize_var).pack(anchor="w", pady=3)
        ttk.Checkbutton(body, text="Inclure la configuration et les profils (facultatif)",
                        variable=configuration_var).pack(anchor="w", pady=3)
        capture_check = ttk.Checkbutton(
            body, text="Inclure les trames brutes déjà capturées (données sensibles possibles)",
            variable=capture_var)
        capture_check.pack(anchor="w", pady=3)
        if not self.shared["advanced_capture"]:
            capture_check.state(["disabled"])
        ttk.Label(body, text=("Les trames brutes ne sont capturées que si le mode avancé est "
                              "activé pendant cette session."), wraplength=430).pack(anchor="w", pady=(5, 10))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Annuler", command=dialog.destroy).pack(side="right", padx=(5, 0))
        ttk.Button(buttons, text="Continuer…", command=lambda: self.export_diagnostic(
            dialog, anonymize_var.get(), configuration_var.get(), capture_var.get()
        )).pack(side="right")
        dialog.geometry(f"{min(520, max(390, self.root.winfo_screenwidth() - 24))}x250")
        dialog.grab_set()

    def export_diagnostic(self, dialog, anonymize, include_configuration, include_capture):
        import datetime
        path = filedialog.asksaveasfilename(
            parent=dialog, title="Exporter le diagnostic",
            initialfile=f"ClickBridge-Diagnostic-{datetime.date.today().isoformat()}.zip",
            defaultextension=".zip", filetypes=(("Archive ZIP", "*.zip"),))
        if not path:
            return
        device_info = {}
        if self.worker:
            for key, driver in self.worker.drivers.items():
                info = driver.get_device_info()
                device_info[key] = {
                    "device_type": info.device_type, "model": info.model,
                    "manufacturer": info.manufacturer, "device_id": info.device_id,
                    "firmware_version": info.firmware_version,
                    "protocol_version": info.protocol_version,
                    "capabilities": sorted(info.capabilities),
                    "connection_state": info.connection_state.value,
                    "compatibility": info.compatibility.value,
                }
        app_state = {
            "status": self.tray_status(), "status_detail": self.current_status_text,
            "active_profile": self.shared["active_profile"],
            "default_profile": self.shared["default_profile"],
        }
        try:
            members = export_diagnostic_zip(
                path, app_state, device_info, self.config_snapshot(), self.current_log_path(),
                anonymize=anonymize, include_configuration=include_configuration,
                advanced_capture=bool(self.shared["advanced_capture"] and include_capture),
                protocol_records=self.diagnostic_history)
            dialog.destroy()
            messagebox.showinfo("Diagnostic exporté",
                                "Archive créée avec :\n" + "\n".join(members),
                                parent=self.config_window)
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("Export impossible", str(exc), parent=dialog)

    def import_configuration(self):
        path = filedialog.askopenfilename(
            parent=self.config_window, title="Importer une configuration",
            filetypes=(("Fichier JSON", "*.json"), ("Tous les fichiers", "*.*")))
        if not path:
            return
        global CONFIG_WRITE_BLOCKED, CONFIG_LOAD_ERROR
        try:
            with open(path, encoding="utf-8") as fh:
                imported = json.load(fh)
            candidate = {**DEFAULTS, **migrate_config_data(imported)}
            candidate["profiles"] = normalize_profiles(
                candidate.get("profiles"), candidate["plus"], candidate["minus"])
            validate_config(candidate)
            backup_config_file(CONFIG_FILE, "pre-import")
            CONFIG_WRITE_BLOCKED = False
            CONFIG_LOAD_ERROR = None
            self.apply_configuration(candidate)
            messagebox.showinfo("Configuration importée", "La configuration a été importée.",
                                parent=self.config_window)
        except (OSError, json.JSONDecodeError, ConfigError, ValueError) as exc:
            messagebox.showerror("Import impossible", str(exc), parent=self.config_window)

    def make_button(self, parent, text, command):
        return tk.Button(parent, text=text, command=command, relief="flat",
                         bg=self.colors["card2"], fg=self.colors["text"],
                         activebackground=self.colors["accent"],
                         activeforeground=self.colors["bg"], padx=12, pady=8,
                         font=("Segoe UI", 9, "bold"), cursor="hand2")

    def open_configuration(self):
        self.config_window.deiconify()
        self.config_window.lift()

    def open_journal(self):
        path = self.current_log_path()
        if path:
            try:
                with open(path, encoding="utf-8") as fh:
                    lines = fh.readlines()[-300:]
                self.log.config(state="normal")
                self.log.delete("1.0", "end")
                self.log.insert("end", "".join(lines))
                if self.diagnostic_history:
                    self.log.insert("end", "\n" + "\n".join(self.diagnostic_history))
                self.log.config(state="disabled")
            except (OSError, TypeError):
                pass
        self.journal_window.deiconify()
        self.journal_window.lift()

    def hide_window(self):
        if self.tray_icon is None:
            self.on_close()
            return
        self.root.withdraw()

    def copy_journal(self):
        path = self.current_log_path()
        file_contents = False
        try:
            with open(path, encoding="utf-8") as fh:
                contents = fh.read()
            file_contents = True
        except (OSError, TypeError):
            contents = self.log.get("1.0", "end-1c")
        if file_contents and self.diagnostic_history:
            contents += "\n\n" + "\n\n".join(self.diagnostic_history)
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(contents)
            self.root.update()
        except tk.TclError:
            pass

    @staticmethod
    def current_log_path():
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                return handler.baseFilename
        return None

    def tray_status(self):
        return {"green": "CONNECTÉ", "orange": "RECHERCHE / CONNEXION",
                "gray": "ARRÊTÉ", "red": "ERREUR"}.get(self.current_status_color, "ÉTAT INCONNU")

    def make_tray_image(self, color):
        if Image is None:
            return None
        image = Image.new("RGBA", (64, 64), (16, 24, 32, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((7, 7, 57, 57), fill=self.COLORS.get(color, self.COLORS["gray"]))
        try:
            font = ImageFont.truetype("arial.ttf", 22)
        except OSError:
            font = ImageFont.load_default()
        draw.text((17, 20), "CB", fill="#101820", font=font)
        return image

    def make_tray_menu(self):
        if pystray is None:
            return None
        profile_items = [pystray.MenuItem(
            "Automatique",
            lambda icon, item: self.root.after(0, lambda: self.select_profile("Automatique")),
            checked=lambda item: self.shared["active_profile"].casefold() == "automatique")]
        for profile in self.shared["profiles"]:
            name = profile["name"]
            profile_items.append(pystray.MenuItem(
                name,
                lambda icon, item, selected=name: self.root.after(
                    0, lambda: self.select_profile(selected)),
                checked=lambda item, selected=name: self.shared["active_profile"].casefold() == selected.casefold()))
        return pystray.Menu(
            pystray.MenuItem(lambda item: f"Click Bridge — {self.tray_status()}", None, enabled=False),
            pystray.MenuItem("Actif", self._tray_toggle_active,
                             checked=lambda item: self.is_active),
            pystray.MenuItem("Profil", pystray.Menu(*profile_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Afficher", self._tray_show, default=True),
            pystray.MenuItem("Pause / reprendre", self._tray_toggle_active),
            pystray.MenuItem("Copier le journal", self._tray_copy),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", self._tray_quit))

    def start_tray(self):
        if pystray is None:
            self.add_log("Zone de notification indisponible : installe pystray et Pillow.")
            return
        try:
            self.tray_icon = pystray.Icon(
                "ClickBridge", self.make_tray_image(self.current_status_color),
                f"Click Bridge — {self.tray_status()}", menu=self.make_tray_menu())
            # pystray documente run_detached pour l'intégration à une boucle Tkinter.
            self.tray_icon.run_detached()
        except Exception as exc:
            self.tray_icon = None
            self.add_log(f"Impossible de créer l'icône de notification : {exc}")

    def update_tray_menu(self):
        if self.tray_icon is None:
            return
        try:
            self.tray_icon.menu = self.make_tray_menu()
            self.tray_icon.update_menu()
        except Exception:
            pass

    def update_tray_status(self):
        if self.tray_icon is None:
            return
        try:
            self.tray_icon.title = f"Click Bridge — {self.tray_status()}"
            self.tray_icon.icon = self.make_tray_image(self.current_status_color)
            self.update_tray_menu()
        except Exception:
            pass

    def _tray_call(self, callback):
        try:
            self.root.after(0, callback)
        except tk.TclError:
            pass

    def _tray_show(self, _icon=None, _item=None):
        self._tray_call(lambda: (self.root.deiconify(), self.root.lift()))

    def _tray_toggle_active(self, _icon=None, _item=None):
        self._tray_call(self.toggle_worker)

    def _tray_copy(self, _icon=None, _item=None):
        self._tray_call(self.copy_journal)

    def _tray_quit(self, _icon=None, _item=None):
        self._tray_call(self.on_close)

    def select_profile(self, name):
        self.active_profile_var.set(name)
        self.active_profile_changed()

    def update_session_stats(self):
        elapsed = self.session_elapsed
        if self.session_started_at is not None:
            elapsed += time.monotonic() - self.session_started_at
        seconds = int(elapsed)
        duration = f"{seconds // 3600:02d}:{(seconds // 60) % 60:02d}:{seconds % 60:02d}"
        total = (self.change_counts["plus"] + self.change_counts["minus"]
                 + self.change_counts["ride"])
        average = total / (elapsed / 60) if elapsed > 0 else 0.0
        self.stat_values["duration"].config(text=duration)
        self.stat_values["changes"].config(text=str(total))
        self.stat_values["plus"].config(text=str(self.change_counts["plus"]))
        self.stat_values["minus"].config(text=str(self.change_counts["minus"]))
        self.stat_values["ride"].config(text=str(self.change_counts["ride"]))
        self.stat_values["average"].config(text=f"{average:.1f}".replace(".", ",") + "/min")

    def load_history(self):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def format_history_duration(self, seconds):
        seconds = max(0, int(seconds))
        hours, minutes = divmod(seconds // 60, 60)
        return f"{hours}h{minutes:02d}" if hours else f"{minutes} min"

    def open_history(self):
        if self.history_window is None or not self.history_window.winfo_exists():
            self.history_window = tk.Toplevel(self.root)
            self.history_window.title("Click Bridge — Historique")
            self.history_window.configure(bg=self.colors["bg"])
            self.history_window.geometry(
                f"{min(600, max(390, self.root.winfo_screenwidth() - 24))}x"
                f"{min(360, max(300, self.root.winfo_screenheight() - 80))}")
            body = tk.Frame(self.history_window, bg=self.colors["bg"], padx=12, pady=12)
            body.pack(fill="both", expand=True)
            style = ttk.Style(self.history_window)
            style.configure("History.Treeview", background=self.colors["card"],
                            foreground=self.colors["text"], fieldbackground=self.colors["card"],
                            rowheight=30, borderwidth=0)
            style.configure("History.Treeview.Heading", background=self.colors["card2"],
                            foreground=self.colors["text"], padding=(9, 7), relief="flat")
            style.map("History.Treeview", background=[("selected", self.colors["accent"])],
                      foreground=[("selected", self.colors["bg"])])
            self.history_table = ttk.Treeview(
                body, columns=("date", "profile", "duration", "changes", "ride"),
                show="headings", style="History.Treeview")
            for column, heading, width in (("date", "Date", 105), ("profile", "Profil", 150),
                                           ("duration", "Durée", 100),
                                           ("changes", "Total", 75), ("ride", "Ride", 65)):
                self.history_table.heading(column, text=heading)
                self.history_table.column(column, width=width, anchor="w")
            self.history_table.pack(fill="both", expand=True)
            self.history_window.protocol("WM_DELETE_WINDOW", self.history_window.withdraw)
        else:
            self.history_window.deiconify()
            self.history_window.lift()
        for row in self.history_table.get_children():
            self.history_table.delete(row)
        for entry in self.load_history():
            try:
                self.history_table.insert("", "end", values=(
                    entry.get("date", ""), entry.get("profile", ""),
                    self.format_history_duration(entry.get("duration_seconds", 0)),
                    entry.get("changes", 0), entry.get("ride", 0)))
            except (TypeError, ValueError):
                continue

    def record_session(self):
        if self.session_saved:
            return
        self.session_saved = True
        if self.session_started_at is not None:
            self.session_elapsed += time.monotonic() - self.session_started_at
            self.session_started_at = None
        changes = (self.change_counts["plus"] + self.change_counts["minus"]
                   + self.change_counts["ride"])
        if changes == 0:
            return
        entry = {"date": datetime.datetime.now().strftime("%d/%m/%Y"),
                 "profile": self.current_profile_name,
                 "duration_seconds": int(self.session_elapsed),
                 "changes": changes, "plus": self.change_counts["plus"],
                 "minus": self.change_counts["minus"],
                 "ride": self.change_counts["ride"]}
        history = self.load_history()
        history.insert(0, entry)
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(HISTORY_FILE, "w", encoding="utf-8") as fh:
                json.dump(history[:100], fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning("Could not save session history: %s", exc)

    def register_button(self, which):
        self.click_button_states[which] = True
        self.change_counts[which] += 1
        button = self.plus_button if which == "plus" else self.minus_button
        color = self.COLORS["green"] if which == "plus" else self.COLORS["minus"]
        button.config(bg=color, fg=self.colors["bg"])
        button.after(180, lambda: self.reset_click_button(which))
        self.update_session_stats()

    def release_button(self, which):
        self.click_button_states[which] = False
        if self.selected_device == "Zwift Click V1":
            self.reset_click_button(which)

    def reset_click_button(self, which):
        self.click_button_states[which] = False
        button = self.plus_button if which == "plus" else self.minus_button
        inactive_color = self.COLORS["green"] if which == "plus" else self.COLORS["minus"]
        button.config(bg=self.colors["card2"], fg=inactive_color)

    def register_ride_button(self, side, name, pressed):
        self.ride_button_values[(side, name)] = pressed
        if self.selected_device == "Zwift Ride":
            self.render_ride_buttons(side)
        if pressed:
            self.change_counts["ride"] += 1
            self.update_session_stats()

    def render_ride_buttons(self, side):
        frame = self.ride_button_frames[side]
        for child in frame.winfo_children():
            child.destroy()
        layouts = {
            "left": (("UP", 0, 1, "↑"), ("LEFT", 1, 0, "←"),
                     ("RIGHT", 1, 2, "→"), ("DOWN", 2, 1, "↓"),
                     ("SHIFT_UP_L", 3, 0, "Levier +"),
                     ("SHIFT_DN_L", 3, 1, "Levier −")),
            "right": (("A", 0, 0, "A"), ("B", 0, 1, "B"),
                      ("Y", 1, 0, "Y"), ("Z", 1, 1, "Z"),
                      ("SHIFT_UP_R", 2, 0, "Levier +"),
                      ("SHIFT_DN_R", 2, 1, "Levier −")),
        }
        for name, row, column, caption in layouts[side]:
            active = self.ride_button_values.get((side, name), False)
            label = RoundedControl(
                frame, caption, self.colors, width=82 if side == "left" else 92,
                height=29, radius=8,
                bg=self.COLORS["green"] if active else self.colors["card"],
                fg=self.colors["bg"] if active else self.colors["text"],
                font=("Segoe UI", 9, "bold"))
            label.grid(row=row, column=column, padx=2, pady=1, sticky="nsew")
            self.ride_button_labels[side][name] = label

    def select_device(self, _event=None):
        self.selected_device = self.device_selector_var.get()
        self.click_panel.pack_forget()
        self.ride_panel.pack_forget()
        if self.selected_device == "Zwift Click V1":
            self.status_detail.pack(before=self.device_panel, pady=(2, 4))
            for which, active in self.click_button_states.items():
                if active:
                    button = self.plus_button if which == "plus" else self.minus_button
                    color = self.COLORS["green"] if which == "plus" else self.COLORS["minus"]
                    button.configure(bg=color, fg=self.colors["bg"])
            self.click_panel.pack(fill="x")
            return
        self.status_detail.pack_forget()
        for button in (self.plus_button, self.minus_button):
            button.configure(bg=self.colors["card2"], fg=self.colors["text"])
        for side in ("left", "right"):
            status_text, color = self.ride_device_statuses[side]
            self.ride_device_status_labels[side].configure(
                text=status_text, fg=self.COLORS.get(color, self.colors["muted"]))
            self._render_ride_battery(side, self.ride_battery_values[side])
            paddle = self.ride_paddle_values[side]
            self.ride_paddle_labels[side].configure(
                text=f"Paddle : {paddle}/200" if paddle is not None else "Paddle : –")
            self.render_ride_buttons(side)
        self.ride_panel.pack(fill="x")

    def start_worker(self):
        if self.is_active:
            return
        self.session_saved = False
        self.worker = Worker(self.queue, self.shared)
        self.is_active = True
        self.session_started_at = time.monotonic()
        self.worker.start()
        self.toggle.config(text="Pause")
        self.update_tray_menu()

    def toggle_worker(self):
        if self.is_active:
            self.is_active = False
            self.worker.stop()
            self.record_session()
            if self.session_started_at is not None:
                self.session_elapsed += time.monotonic() - self.session_started_at
                self.session_started_at = None
            self.toggle.config(text="Reprendre")
        else:
            self.start_worker()
        self.update_session_stats()
        self.update_tray_menu()

    def set_status(self, text, color):
        self.current_status_color = color
        self.current_status_text = text
        self.status.config(text=self.tray_status(), fg=self.COLORS.get(color, self.colors["text"]))
        self.status_dot.config(fg=self.COLORS.get(color, self.colors["muted"]))
        self.status_detail.config(text=text)
        self.update_tray_status()

    def set_device_status(self, key, text, color):
        if key == "click":
            self.click_device_status.configure(
                text=text, fg=self.COLORS.get(color, self.colors["muted"]))
            return
        elif key in ("ride_left", "ride_right"):
            side = key.split("_", 1)[1]
            self.ride_device_statuses[side] = (text, color)
            if self.selected_device == "Zwift Ride":
                self.ride_device_status_labels[side].configure(
                    text=text, fg=self.COLORS.get(color, self.colors["muted"]))
            return
        else:
            return

    def show_ride_battery(self, side, pct):
        self.ride_battery_values[side] = pct
        if self.selected_device == "Zwift Ride":
            self._render_ride_battery(side, pct)

    def _render_ride_battery(self, side, pct):
        label = self.ride_battery_labels[side]
        if pct is None:
            label.configure(text="Batterie : –", fg=self.colors["muted"])
            self.ride_battery_alerted[side] = False
            return
        if not isinstance(pct, int) or not 0 <= pct <= 100:
            self.add_log(f"Batterie Ride {side} invalide ignorée : {pct!r}")
            return
        low = self.shared["battery_low"] > 0 and pct <= self.shared["battery_low"]
        label.configure(text=f"Batterie : {pct} %" + (" ⚠ faible" if low else ""),
                         fg=self.COLORS["red"] if low else self.colors["muted"])
        if low and not self.ride_battery_alerted[side]:
            self.ride_battery_alerted[side] = True
            self.add_log(f"⚠ Batterie Ride {side} faible : {pct} %")
        elif not low:
            self.ride_battery_alerted[side] = False

    def add_log(self, text):
        self.log.config(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 300:
            self.log.delete("1.0", f"{lines - 300}.0")
        self.log.see("end")
        self.log.config(state="disabled")

    def add_diagnostic(self, uuid, wire_payload, decoded_payload, interpreted, mapped):
        details = ["Bluetooth event", f"UUID: {uuid}", f"Payload: {wire_payload or '—'}"]
        if decoded_payload:
            details.append(f"Decoded payload: {decoded_payload}")
        details.extend((f"Interpreted as: {interpreted}", f"Mapped to: {mapped}"))
        record = f"{time.strftime('%H:%M:%S')}  " + "\n".join(details)
        self.diagnostic_history.append(record)
        self.diagnostic_history = self.diagnostic_history[-50:]
        self.add_log("\n".join(details))

    def show_battery(self, pct):
        if pct is None:
            self.battery.config(text="Batterie Click : –", fg=self.colors["muted"])
            return
        if not isinstance(pct, int) or not 0 <= pct <= 100:
            self.add_log(f"Niveau de batterie invalide ignoré : {pct!r}")
            return
        threshold = self.shared["battery_low"]
        low = threshold > 0 and pct <= threshold
        if low:
            self.battery.config(text=f"Batterie Click : {pct} %  ⚠ faible", fg=self.COLORS["red"])
            if not self.battery_alerted:
                self.battery_alerted = True
                self.add_log(f"⚠ Batterie faible : {pct} %")
                try:
                    import winsound
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                except Exception:
                    pass
        else:
            self.battery.config(text=f"Batterie Click : {pct} %", fg=self.colors["muted"])
            self.battery_alerted = False

    def poll(self):
        now = time.time()
        elapsed_since_poll = now - self.last_poll_at
        self.last_poll_at = now
        if elapsed_since_poll >= 5.0 and self.is_active and self.worker:
            # Tk reprend après la veille avec un grand écart d'horloge. Interrompre le
            # scan/ancienne session force DeviceManager à détecter à nouveau le Click.
            logger.info("Windows resume inferred from application timer")
            self.worker.request_reconnect()
        try:
            while True:
                kind, *args = self.queue.get_nowait()
                if kind == "status":
                    self.set_status(*args)
                elif kind == "status_detail":
                    self.status_detail.configure(text=args[0])
                elif kind == "device_status":
                    self.set_device_status(*args)
                elif kind == "log":
                    self.add_log(args[0])
                elif kind == "battery":
                    self.show_battery(args[0])
                elif kind == "device_battery":
                    key, pct = args
                    self.show_ride_battery(key.split("_", 1)[1], pct)
                elif kind == "press":
                    self.last_action_text = args[0]
                    self.last.config(text=f"Dernière action : {args[0]}")
                elif kind == "button":
                    self.register_button(args[0])
                elif kind == "ride_release":
                    self.release_button(args[0])
                elif kind == "ride_button":
                    self.register_ride_button(*args)
                elif kind == "ride_paddle":
                    side, value = args
                    self.ride_paddle_values[side] = value
                    if self.selected_device == "Zwift Ride":
                        self.ride_paddle_labels[side].configure(
                            text=f"Paddle : {value}/200" if value is not None
                            else "Paddle : –")
                elif kind == "profile":
                    self.current_profile_name = args[0]
                    self.profile_status.config(text=f"Profil effectif : {args[0]}")
                elif kind == "diagnostic":
                    self.add_diagnostic(*args)
                elif kind == "update_check":
                    self.update_button.state(["!disabled"])
                    self.update_button.configure(text="Vérifier les mises à jour")
                    self.show_update_result(args[0])
                elif kind == "update_check_error":
                    self.update_button.state(["!disabled"])
                    self.update_button.configure(text="Vérifier les mises à jour")
                    messagebox.showerror("Vérification impossible", args[0],
                                         parent=self.config_window)
                elif kind == "update_download":
                    self.finish_update_download(*args)
        except queue.Empty:
            pass
        self.update_session_stats()
        self.root.after(100, self.poll)

    def on_close(self):
        logger.info("Application stopped")
        self.record_session()
        self.save_config()
        if self.worker:
            self.worker.stop()
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    configure_logging()
    logger.info("Application started")
    root = tk.Tk()
    if already_running():
        root.withdraw()
        messagebox.showinfo("ClickBridge",
                            "ClickBridge est déjà lancé.\n"
                            "Une seule instance peut utiliser le Click à la fois.")
        root.destroy()
    else:
        App(root)
        root.mainloop()
