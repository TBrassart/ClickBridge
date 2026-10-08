"""Création d'archives de diagnostic avec contrôle de données sensibles."""
import copy
import json
import os
import platform
import re
import zipfile
from datetime import datetime
from app_version import APP_VERSION


MAX_LOG_BYTES = 2 * 1024 * 1024
MAC_PATTERN = re.compile(r"(?i)\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b")
WINDOWS_USER_PATH = re.compile(r"(?i)([A-Z]:\\Users\\)[^\\\s]+")
WINDOWS_PROFILE = re.compile(r"(?i)C:\\Users\\[^\\\s]+")
PAYLOAD_LINE = re.compile(r"(?i)((?:decoded )?payload:\s*|brut=)([0-9a-f ]+)")
UNREADABLE_FRAME = re.compile(r"(?i)(trame illisible\s*:\s*)[0-9a-f]+")
DECODED_FRAME = re.compile(r"(?i)(type=0x[0-9a-f]+\s+champs=).*")


def _redact_text(value, sensitive_values, anonymize):
    text = str(value)
    if not anonymize:
        return text
    text = MAC_PATTERN.sub("[ADRESSE_BLUETOOTH]", text)
    text = WINDOWS_USER_PATH.sub(r"\1[UTILISATEUR]", text)
    text = WINDOWS_PROFILE.sub(r"C:\\Users\\[UTILISATEUR]", text)
    text = PAYLOAD_LINE.sub(r"\1[PAYLOAD_MASQUÉ]", text)
    text = UNREADABLE_FRAME.sub(r"\1[PAYLOAD_MASQUÉ]", text)
    text = DECODED_FRAME.sub(r"\1[TRAME_MASQUÉE]", text)
    for sensitive in sorted((s for s in sensitive_values if s), key=len, reverse=True):
        text = re.sub(re.escape(sensitive), "[PROFIL]", text, flags=re.IGNORECASE)
    return text


def _sanitize(value, sensitive_values, anonymize):
    if isinstance(value, dict):
        return {str(key): _sanitize(item, sensitive_values, anonymize)
                for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_sanitize(item, sensitive_values, anonymize) for item in value]
    if isinstance(value, str):
        return _redact_text(value, sensitive_values, anonymize)
    return value


def _read_log(path):
    if not path:
        return ""
    try:
        with open(path, "rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - MAX_LOG_BYTES))
            data = stream.read(MAX_LOG_BYTES)
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def build_diagnostic_data(app_state, device_info, config, log_path,
                         anonymize=True, include_configuration=False,
                         advanced_capture=False, protocol_records=()):
    """Assemble les sections de diagnostic sans écrire de données sur disque."""
    profiles = config.get("profiles", []) if isinstance(config, dict) else []
    sensitive = []
    if isinstance(profiles, list):
        for profile in profiles:
            if isinstance(profile, dict):
                sensitive.extend((str(profile.get("name", "")),
                                  str(profile.get("application", ""))))
    sensitive = [value for value in sensitive if value]

    raw_log = _read_log(log_path)
    application_log = _redact_text(raw_log, sensitive, anonymize)
    error_log = "\n".join(
        line for line in application_log.splitlines()
        if re.search(r"\b(?:WARNING|ERROR|CRITICAL)\b", line))

    device = _sanitize(copy.deepcopy(device_info or {}), sensitive, anonymize)
    if anonymize and isinstance(device, dict):
        device["device_id"] = "[ANONYMISÉ]" if device.get("device_id") else ""

    state = dict(app_state or {})
    active_profile = state.get("active_profile", "Automatique")
    state["active_profile"] = _redact_text(active_profile, sensitive, anonymize)
    state["default_profile"] = _redact_text(state.get("default_profile", ""), sensitive, anonymize)
    state["status_detail"] = _redact_text(state.get("status_detail", ""), sensitive, anonymize)
    state["device"] = device

    data = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "application": {
            "name": "Click Bridge",
            "version": APP_VERSION,
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "windows": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
        },
        "bluetooth": {
            "status": state.get("status", "inconnu"),
            "detail": state.get("status_detail", ""),
            "advanced_capture_enabled": bool(advanced_capture),
            "adapter_status": "Non interrogé directement par l'application",
        },
        "devices": {
            "click_v1": {"supported": True, "info": device},
            "click_v2": {"supported": False, "status": "Non implémenté"},
            "play": {"supported": False, "status": "Non implémenté"},
            "ride": {"supported": False, "status": "Non implémenté"},
        },
        "profiles": {
            "count": len(profiles) if isinstance(profiles, list) else 0,
            "active": state["active_profile"],
            "default": state["default_profile"],
            "automatic_selection": str(state["active_profile"]).casefold() == "automatique",
        },
        "configuration": {
            "available": bool(config),
            "included_in_archive": bool(include_configuration),
            "anonymized": bool(anonymize),
        },
        "errors": {
            "count": sum(bool(re.search(r"\b(?:WARNING|ERROR|CRITICAL)\b", line))
                          for line in application_log.splitlines()),
        },
    }
    if include_configuration:
        data["configuration"]["values"] = _sanitize(copy.deepcopy(config), sensitive, anonymize)
    if advanced_capture and protocol_records:
        data["protocol_capture"] = "included as protocol-capture.log when selected"
    capture = "\n\n".join(str(record) for record in protocol_records) if advanced_capture else ""
    if anonymize and capture:
        capture = _redact_text(capture, sensitive, True)
    return data, application_log, error_log, device, capture


def export_diagnostic_zip(path, app_state, device_info, config, log_path,
                          anonymize=True, include_configuration=False,
                          advanced_capture=False, protocol_records=()):
    """Écrit l'archive demandée et retourne sa liste de membres."""
    data, application_log, error_log, device, capture = build_diagnostic_data(
        app_state, device_info, config, log_path, anonymize,
        include_configuration, advanced_capture, protocol_records)
    compatibility = {
        "click_v1": {"supported": True, "status": device.get("compatibility", "unknown")},
        "click_v2": {"supported": False, "status": "Non implémenté"},
        "play": {"supported": False, "status": "Non implémenté"},
        "ride": {"supported": False, "status": "Non implémenté"},
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostic.json", json.dumps(data, ensure_ascii=False, indent=2))
        archive.writestr("application.log", application_log or "Aucun journal disponible.\n")
        archive.writestr("device-info.json", json.dumps(device, ensure_ascii=False, indent=2))
        archive.writestr("compatibility.json", json.dumps(compatibility, ensure_ascii=False, indent=2))
        archive.writestr("errors.log", error_log or "Aucune erreur ou alerte enregistrée.\n")
        if capture:
            archive.writestr("protocol-capture.log", capture + "\n")
    return ["diagnostic.json", "application.log", "device-info.json",
            "compatibility.json", "errors.log"] + (["protocol-capture.log"] if capture else [])
