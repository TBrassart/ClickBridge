"""ClickBridge : Zwift Click V1 (firmware chiffré) -> touches clavier, avec interface."""
import asyncio
import copy
import datetime
import json
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
from devices import ClickV1Driver, DeviceManager
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
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    pystray = None
    Image = ImageDraw = ImageFont = None

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
        return ("Le Click n'a pas répondu à temps. Réveille-le (appui sur un bouton) "
                "et rapproche-le du PC.", "orange")
    if "denied" in low:
        return ("Accès refusé : le Click est sans doute déjà connecté à une autre "
                "application (Zwift, Companion, téléphone) ou à Windows. Ferme-les, "
                "puis réveille le Click.", "red")
    if any(w in low for w in ("adapter", "radio", "not available", "turned off",
                              "powered off", "bluetooth")):
        return ("Bluetooth indisponible : vérifie que le Bluetooth est activé dans "
                "Windows (mode avion désactivé) et qu'un adaptateur est présent.", "red")
    if any(w in low for w in ("disconnect", "not connected", "unreachable")):
        return ("Connexion perdue avec le Click. Réveille-le et patiente quelques secondes.",
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
        self.last_battery = None
        self.event_engine = EventEngine()
        self.last_profile_name = None
        self.driver = ClickV1Driver(
            verbose=lambda: self.shared["verbose"],
            status=lambda *args: self.emit("status", *args),
            battery=self.on_battery, log=self.on_driver_log,
            diagnostic=lambda *args: self.emit("diagnostic", *args),
            tick=lambda: self.publish_events(self.event_engine.advance()))
        self.device_manager = DeviceManager([self.driver])

    def emit(self, *msg):
        self.q.put(msg)

    def report(self, msg, detail=None):
        """Écrit un message dans le journal une seule fois tant qu'il ne change pas."""
        if msg != self.last_error:
            self.last_error = msg
            self.emit("log", msg)
            logger.warning("%s%s", msg, f" ({detail})" if detail else "")

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
                    self.emit("status", "Reprise de Windows : nouvelle recherche du Click…", "orange")
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
        self.emit("status", "Recherche du Click… appuie sur un bouton (LED bleue)", "orange")
        self.emit("battery", None)
        if not self.search_logged:
            logger.info("Searching for Zwift Click")
            self.search_logged = True
        try:
            result = await self.device_manager.run_once(self.on_device_event)
        finally:
            self.state = {"plus": False, "minus": False}
            for task in list(self.tasks):
                task.cancel()
            self.event_engine.reset()
        if result is None:
            self.not_found += 1
            msg = "Click introuvable : appuie sur un bouton jusqu'à ce que la LED pulse en bleu."
            if self.not_found >= 3:
                msg += (" Vérifie aussi qu'aucune autre appli (Zwift, Companion, téléphone) "
                        "n'est connectée au Click.")
            self.report(msg)
            return msg, "orange"
        self.not_found = 0
        self.search_logged = False
        return result or ("Click déconnecté : réveille-le (appui sur un bouton)", "orange")

    def on_battery(self, pct):
        self.emit("battery", pct)
        if pct != self.last_battery:
            logger.info("Battery: %d%%", pct)
            self.last_battery = pct

    def on_driver_log(self, message):
        self.emit("log", message)
        if (message in ("Clé de l'appareil reçue", "Click déconnecté")
                or message.startswith("Connecté à ")):
            logger.info(message)

    def on_device_event(self, event, wire_payload=None, decoded_payload=None):
        """Seuls les événements normalisés du pilote entrent dans le moteur de gestes."""
        derived = self.event_engine.feed(event)
        self.publish_events(derived, wire_payload=wire_payload,
                            decoded_payload=decoded_payload)
        if event.type in (EventType.PLUS_DOWN, EventType.MINUS_DOWN):
            which = "plus" if event.type == EventType.PLUS_DOWN else "minus"
            self.emit("button", which)
            logger.info("BUTTON_%s", which.upper())

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
            if self.shared["verbose"]:
                self.emit("log", f"Événement : {event.type.value}")
            action = actions.get(event_name, "").strip()
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
    COLORS = {"green": "#2ecc71", "orange": "#f5a623", "gray": "#aab4bd", "red": "#ff5c65"}

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

        self.colors = {"bg": "#101820", "card": "#1a2732", "card2": "#22323f",
                       "text": "#f1f5f8", "muted": "#9aabb8", "accent": "#54d6a1",
                       "green": "#2ecc71", "orange": "#f5a623", "gray": "#aab4bd",
                       "red": "#ff5c65"}
        root.configure(bg=self.colors["bg"])
        root.geometry("420x560")
        root.minsize(380, 520)
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
        style.configure("TEntry", fieldbackground=self.colors["card2"], foreground=self.colors["text"])
        style.configure("TSpinbox", fieldbackground=self.colors["card2"], foreground=self.colors["text"])
        style.configure("TCombobox", fieldbackground=self.colors["card2"],
                        background=self.colors["card2"], foreground=self.colors["text"])
        style.configure("Dark.TCombobox", fieldbackground=self.colors["card2"],
                        background=self.colors["card2"], foreground=self.colors["text"])

        self.is_active = False
        self.session_elapsed = 0.0
        self.session_started_at = None
        self.change_counts = {"plus": 0, "minus": 0}
        self.diagnostic_history = []
        self.last_action_text = "–"
        self.current_profile_name = self.shared["default_profile"]
        self.session_saved = False
        self.history_window = None
        self.tray_icon = None
        self.current_status_color = "orange"
        self.current_status_text = "Recherche du Click…"
        self.last_poll_at = time.time()

        main = tk.Frame(root, bg=self.colors["bg"], padx=18, pady=10)
        main.pack(fill="both", expand=True)
        header = tk.Frame(main, bg=self.colors["bg"])
        header.pack(fill="x")
        tk.Label(header, text="Click Bridge", bg=self.colors["bg"], fg=self.colors["text"],
                 font=("Segoe UI", 18, "bold")).pack(side="left")

        hero = tk.Frame(main, bg=self.colors["card"], padx=12, pady=10)
        hero.pack(fill="x", pady=(8, 8))
        status_row = tk.Frame(hero, bg=self.colors["card"])
        status_row.pack()
        self.status_dot = tk.Label(status_row, text="●", bg=self.colors["card"],
                                   fg=self.colors["orange"], font=("Segoe UI", 17))
        self.status_dot.pack(side="left", padx=(0, 8))
        self.status = tk.Label(status_row, text="RECHERCHE / CONNEXION", bg=self.colors["card"],
                               fg=self.colors["orange"], font=("Segoe UI", 11, "bold"))
        self.status.pack(side="left")
        self.status_detail = tk.Label(hero, text="Recherche du Click…", bg=self.colors["card"],
                                      fg=self.colors["muted"], font=("Segoe UI", 9), wraplength=340)
        self.status_detail.pack(pady=(2, 4))
        tk.Label(hero, text="Zwift Click V1", bg=self.colors["card"], fg=self.colors["text"],
                 font=("Segoe UI", 14, "bold")).pack(pady=(4, 1))
        self.battery = tk.Label(hero, text="Batterie : –", bg=self.colors["card"],
                                fg=self.colors["muted"], font=("Segoe UI", 10))
        self.battery.pack()

        buttons = tk.Frame(hero, bg=self.colors["card"])
        buttons.pack(pady=(8, 6))
        self.plus_button = tk.Button(buttons, text="+", width=7, height=1, relief="flat",
                                     bg=self.colors["card2"], fg=self.colors["text"],
                                     activebackground=self.colors["accent"],
                                     activeforeground=self.colors["bg"],
                                     disabledforeground=self.colors["text"],
                                     font=("Segoe UI", 17, "bold"), state="disabled")
        self.plus_button.pack(side="left", padx=18)
        self.minus_button = tk.Button(buttons, text="−", width=7, height=1, relief="flat",
                                      bg=self.colors["card2"], fg=self.colors["text"],
                                      activebackground=self.colors["accent"],
                                      activeforeground=self.colors["bg"],
                                      disabledforeground=self.colors["text"],
                                      font=("Segoe UI", 17, "bold"), state="disabled")
        self.minus_button.pack(side="left", padx=18)
        self.last = tk.Label(hero, text="Dernière action : –", bg=self.colors["card"],
                             fg=self.colors["muted"], font=("Segoe UI", 10))
        self.last.pack(pady=(0, 0))

        profile_card = tk.Frame(main, bg=self.colors["card"], padx=10, pady=6)
        profile_card.pack(fill="x", pady=(0, 7))
        profile_head = tk.Frame(profile_card, bg=self.colors["card"])
        profile_head.pack(fill="x")
        tk.Label(profile_head, text="Profil actif", bg=self.colors["card"], fg=self.colors["muted"],
                 font=("Segoe UI", 9)).pack(side="left")
        self.active_profile_var = tk.StringVar(value=self.shared["active_profile"])
        self.active_profile_combo = ttk.Combobox(
            profile_head, textvariable=self.active_profile_var, state="readonly", width=22,
            style="Dark.TCombobox")
        self.active_profile_combo.pack(side="right")
        self.active_profile_combo.bind("<<ComboboxSelected>>", self.active_profile_changed)
        default_row = tk.Frame(profile_card, bg=self.colors["card"])
        default_row.pack(fill="x", pady=(3, 0))
        tk.Label(default_row, text="Par défaut", bg=self.colors["card"], fg=self.colors["muted"],
                 font=("Segoe UI", 9)).pack(side="left")
        self.default_profile_var = tk.StringVar(value=self.shared["default_profile"])
        self.default_profile_combo = ttk.Combobox(
            default_row, textvariable=self.default_profile_var, state="readonly", width=22,
            style="Dark.TCombobox")
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

        stats = tk.Frame(main, bg=self.colors["card"], padx=12, pady=8)
        stats.pack(fill="x")
        stats_header = tk.Frame(stats, bg=self.colors["card"])
        stats_header.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 3))
        tk.Label(stats_header, text="Session", bg=self.colors["card"], fg=self.colors["text"],
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Button(stats_header, text="Historique", command=self.open_history, relief="flat",
                  bg=self.colors["card"], fg=self.colors["accent"], activebackground=self.colors["card"],
                  font=("Segoe UI", 9, "underline")).pack(side="right")
        self.stat_values = {}
        stat_rows = (("duration", "Durée", 1, 0), ("changes", "Changements", 2, 0),
                     ("plus", "+", 3, 0), ("minus", "−", 3, 2),
                     ("average", "Moyenne", 1, 2))
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
        self.config_window.geometry("500x680")
        self.config_window.protocol("WM_DELETE_WINDOW", self.config_window.withdraw)
        diagnostics = ttk.LabelFrame(config_body, text="Diagnostic avancé")
        diagnostics.pack(fill="x", pady=(0, 5))
        self.verbose_var = tk.BooleanVar(value=self.shared["advanced_capture"])
        ttk.Checkbutton(
            diagnostics,
            text="Capture protocole / diagnostic avancé (session uniquement)",
            variable=self.verbose_var,
            command=self.set_advanced_capture
        ).pack(anchor="w", padx=8, pady=4)
        ttk.Label(diagnostics, text=("Désactivé par défaut. Peut inclure des trames Bluetooth "
                                     "brutes dans le journal et l'export."),
                  wraplength=420).pack(anchor="w", padx=8, pady=(0, 5))
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
            windows_options, text="Lancer ClickBridge au démarrage de Windows",
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
            side="left", padx=8, pady=6)
        self.update_button = ttk.Button(update_options, text="Vérifier les mises à jour",
                                        command=self.check_for_updates)
        self.update_button.pack(side="right", padx=8, pady=6)

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
        self.journal_window.geometry("560x420")
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
            subprocess.Popen([path, "/RESTARTAPP"], cwd=os.path.dirname(path), close_fds=True)
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
        dialog.geometry("520x250")
        dialog.grab_set()

    def export_diagnostic(self, dialog, anonymize, include_configuration, include_capture):
        import datetime
        path = filedialog.asksaveasfilename(
            parent=dialog, title="Exporter le diagnostic",
            initialfile=f"ClickBridge-Diagnostic-{datetime.date.today().isoformat()}.zip",
            defaultextension=".zip", filetypes=(("Archive ZIP", "*.zip"),))
        if not path:
            return
        info = self.worker.driver.get_device_info() if self.worker else None
        device_info = {}
        if info is not None:
            device_info = {
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
        total = self.change_counts["plus"] + self.change_counts["minus"]
        average = total / (elapsed / 60) if elapsed > 0 else 0.0
        self.stat_values["duration"].config(text=duration)
        self.stat_values["changes"].config(text=str(total))
        self.stat_values["plus"].config(text=str(self.change_counts["plus"]))
        self.stat_values["minus"].config(text=str(self.change_counts["minus"]))
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
            self.history_window.geometry("600x360")
            body = tk.Frame(self.history_window, bg=self.colors["bg"], padx=12, pady=12)
            body.pack(fill="both", expand=True)
            style = ttk.Style(self.history_window)
            style.configure("History.Treeview", background=self.colors["card"],
                            foreground=self.colors["text"], fieldbackground=self.colors["card"])
            style.configure("History.Treeview.Heading", background=self.colors["card2"],
                            foreground=self.colors["text"])
            self.history_table = ttk.Treeview(
                body, columns=("date", "profile", "duration", "changes"),
                show="headings", style="History.Treeview")
            for column, heading, width in (("date", "Date", 105), ("profile", "Profil", 170),
                                           ("duration", "Durée", 100), ("changes", "Changements", 120)):
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
                    entry.get("changes", 0)))
            except (TypeError, ValueError):
                continue

    def record_session(self):
        if self.session_saved:
            return
        self.session_saved = True
        if self.session_started_at is not None:
            self.session_elapsed += time.monotonic() - self.session_started_at
            self.session_started_at = None
        changes = self.change_counts["plus"] + self.change_counts["minus"]
        if changes == 0:
            return
        entry = {"date": datetime.datetime.now().strftime("%d/%m/%Y"),
                 "profile": self.current_profile_name,
                 "duration_seconds": int(self.session_elapsed),
                 "changes": changes, "plus": self.change_counts["plus"],
                 "minus": self.change_counts["minus"]}
        history = self.load_history()
        history.insert(0, entry)
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(HISTORY_FILE, "w", encoding="utf-8") as fh:
                json.dump(history[:100], fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning("Could not save session history: %s", exc)

    def register_button(self, which):
        self.change_counts[which] += 1
        button = self.plus_button if which == "plus" else self.minus_button
        color = self.COLORS["green"] if which == "plus" else self.COLORS["orange"]
        button.config(bg=color, fg=self.colors["bg"])
        button.after(180, lambda: button.config(bg=self.colors["card2"], fg=self.colors["text"]))
        self.update_session_stats()

    def start_worker(self):
        if self.is_active:
            return
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
            self.battery.config(text="Batterie : –", fg=self.colors["muted"])
            return
        if not isinstance(pct, int) or not 0 <= pct <= 100:
            self.add_log(f"Niveau de batterie invalide ignoré : {pct!r}")
            return
        threshold = self.shared["battery_low"]
        low = threshold > 0 and pct <= threshold
        if low:
            self.battery.config(text=f"Batterie : {pct} %  ⚠ faible", fg=self.COLORS["red"])
            if not self.battery_alerted:
                self.battery_alerted = True
                self.add_log(f"⚠ Batterie faible : {pct} %")
                try:
                    import winsound
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                except Exception:
                    pass
        else:
            self.battery.config(text=f"Batterie : {pct} %", fg=self.colors["muted"])
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
                elif kind == "log":
                    self.add_log(args[0])
                elif kind == "battery":
                    self.show_battery(args[0])
                elif kind == "press":
                    self.last_action_text = args[0]
                    self.last.config(text=f"Dernière action : {args[0]}")
                elif kind == "button":
                    self.register_button(args[0])
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
