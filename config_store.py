"""Validation, migrations et sauvegardes sûres du fichier de configuration."""
import copy
import json
import os
import shutil
import tempfile
from datetime import datetime

from profiles import make_legacy_profile

CURRENT_CONFIG_VERSION = 3


class ConfigError(ValueError):
    pass


def _migrate_v1_to_v2(config):
    migrated = copy.deepcopy(config)
    plus = migrated.get("plus", "k")
    minus = migrated.get("minus", "i")
    profiles = migrated.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        profiles = [make_legacy_profile(plus, minus)]
    migrated["profiles"] = profiles
    default_name = profiles[0].get("name", "MyWhoosh") if isinstance(profiles[0], dict) else "MyWhoosh"
    migrated.setdefault("default_profile", default_name)
    migrated.setdefault("active_profile", "Automatique")
    migrated["configVersion"] = 2
    return migrated


def _migrate_v2_to_v3(config):
    migrated = copy.deepcopy(config)
    migrated.setdefault("launch_at_startup", False)
    migrated.setdefault("start_minimized", False)
    migrated["configVersion"] = 3
    return migrated


MIGRATIONS = {1: _migrate_v1_to_v2, 2: _migrate_v2_to_v3}


def validate_config(config):
    if not isinstance(config, dict):
        raise ConfigError("La configuration doit être un objet JSON.")
    version = config.get("configVersion")
    if version != CURRENT_CONFIG_VERSION or isinstance(version, bool):
        raise ConfigError(f"Version de configuration invalide : {version!r}.")
    string_fields = ("plus", "minus", "active_profile", "default_profile")
    for key in string_fields:
        if key in config and not isinstance(config[key], str):
            raise ConfigError(f"Le champ {key} doit être du texte.")
    for key, (minimum, maximum) in {
        "hold_ms": (10, 500), "repeat_delay": (100, 3000),
        "repeat_interval": (30, 1000), "battery_low": (0, 50),
    }.items():
        value = config.get(key, {"hold_ms": 50, "repeat_delay": 400,
                                 "repeat_interval": 120, "battery_low": 20}[key])
        if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
            raise ConfigError(f"Valeur invalide pour {key} : {value!r}.")
    for key in ("repeat", "launch_at_startup", "start_minimized"):
        if key in config and not isinstance(config[key], bool):
            raise ConfigError(f"Le champ {key} doit être vrai ou faux.")
    profiles = config.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ConfigError("Il faut au moins un profil valide.")
    seen = set()
    names = set()
    for index, profile in enumerate(profiles, start=1):
        if not isinstance(profile, dict):
            raise ConfigError(f"Le profil {index} est invalide.")
        name = profile.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"Le profil {index} n'a pas de nom valide.")
        folded = name.strip().casefold()
        if folded in seen:
            raise ConfigError(f"Le nom de profil « {name} » est dupliqué.")
        seen.add(folded)
        names.add(folded)
        if not isinstance(profile.get("application", ""), str):
            raise ConfigError(f"L'application du profil « {name} » doit être du texte.")
        actions = profile.get("actions", {})
        if not isinstance(actions, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                                for k, v in actions.items()):
            raise ConfigError(f"Les actions du profil « {name} » sont invalides.")
    active = config.get("active_profile", "Automatique")
    default = config.get("default_profile", profiles[0]["name"])
    if active.casefold() != "automatique" and active.casefold() not in names:
        raise ConfigError(f"Le profil actif « {active} » n'existe pas.")
    if default.casefold() not in names:
        raise ConfigError(f"Le profil par défaut « {default} » n'existe pas.")
    return config


def _backup_path(config_path, version):
    folder = os.path.join(os.path.dirname(config_path), "backups")
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return os.path.join(folder, f"config-v{version}-{stamp}.json")


def backup_config_file(path, version="current"):
    if not os.path.exists(path):
        return None
    backup = _backup_path(path, version)
    shutil.copy2(path, backup)
    return backup


def _atomic_write(path, text):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    handle, temp_path = tempfile.mkstemp(prefix="config-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


def load_config_file(path):
    """Charge, migre en mémoire, sauvegarde avant migration et valide."""
    with open(path, encoding="utf-8") as stream:
        original = json.load(stream)
    if not isinstance(original, dict):
        raise ConfigError("La configuration doit être un objet JSON.")
    version = original.get("configVersion")
    if version is None:
        # Les profils ont été ajoutés avant l'introduction des versions.
        version = 2 if "profiles" in original else 1
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ConfigError(f"Version de configuration invalide : {version!r}.")
    if version > CURRENT_CONFIG_VERSION:
        raise ConfigError(
            f"La configuration v{version} vient d'une version plus récente de ClickBridge.")
    backup = None
    if version < CURRENT_CONFIG_VERSION:
        backup = backup_config_file(path, version)
    migrated = copy.deepcopy(original)
    while version < CURRENT_CONFIG_VERSION:
        migrated = MIGRATIONS[version](migrated)
        version += 1
    validate_config(migrated)
    return migrated, backup


def migrate_config_data(original):
    """Migre un objet importé sans toucher au disque."""
    if not isinstance(original, dict):
        raise ConfigError("La configuration doit être un objet JSON.")
    version = original.get("configVersion")
    if version is None:
        version = 2 if "profiles" in original else 1
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ConfigError(f"Version de configuration invalide : {version!r}.")
    if version > CURRENT_CONFIG_VERSION:
        raise ConfigError(
            f"La configuration v{version} vient d'une version plus récente de ClickBridge.")
    migrated = copy.deepcopy(original)
    while version < CURRENT_CONFIG_VERSION:
        migrated = MIGRATIONS[version](migrated)
        version += 1
    return validate_config(migrated)


def save_config_file(path, config):
    candidate = copy.deepcopy(config)
    candidate["configVersion"] = CURRENT_CONFIG_VERSION
    validate_config(candidate)
    _atomic_write(path, json.dumps(candidate, ensure_ascii=False, indent=2) + "\n")


def restore_config_file(config_path, backup_path):
    """Valide la sauvegarde, protège la configuration actuelle puis la restaure."""
    with open(backup_path, encoding="utf-8") as stream:
        restored = migrate_config_data(json.load(stream))
    backup_config_file(config_path, "pre-restore")
    save_config_file(config_path, restored)
    return restored
