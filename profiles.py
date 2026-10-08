"""Stockage, sélection et édition des profils Click Bridge."""
import copy
import ctypes
import os
import tkinter as tk
from tkinter import messagebox, ttk


ACTION_FIELDS = (
    ("plus_down", "Bouton + enfoncé"),
    ("minus_down", "Bouton − enfoncé"),
    ("plus_short", "Appui court +"),
    ("minus_short", "Appui court −"),
    ("plus_long", "Appui long +"),
    ("minus_long", "Appui long −"),
    ("plus_double", "Double appui +"),
    ("minus_double", "Double appui −"),
    ("combination", "Deux boutons ensemble"),
    ("sequence", "Séquence de gestes"),
)


def make_legacy_profile(plus="k", minus="i"):
    """Profil initial qui conserve l'envoi immédiat des versions précédentes."""
    return {
        "name": "MyWhoosh",
        "application": "MyWhoosh.exe",
        "actions": {"plus_down": plus, "minus_down": minus},
    }


def normalize_profiles(profiles, plus="k", minus="i"):
    if not isinstance(profiles, list):
        profiles = []
    normalized, names = [], set()
    for item in profiles:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name or name.casefold() in names:
            continue
        actions = item.get("actions", {})
        if not isinstance(actions, dict):
            actions = {}
        normalized.append({
            "name": name,
            "application": str(item.get("application", "")).strip(),
            "actions": {str(k).lower(): str(v).strip()
                        for k, v in actions.items() if v is not None},
        })
        names.add(name.casefold())
    if not normalized:
        normalized = [make_legacy_profile(plus, minus)]
    return normalized


def foreground_executable():
    """Retourne le nom de l'exécutable de la fenêtre Windows au premier plan."""
    if os.name != "nt":
        return ""
    handle = None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.QueryFullProcessImageNameW.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        handle = kernel32.OpenProcess(0x1000, False, process_id.value)
        if not handle:
            return ""
        buffer = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return os.path.basename(buffer.value).casefold()
    except Exception:
        return ""
    finally:
        if handle:
            try:
                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)
            except Exception:
                pass


def resolve_profile(profiles, active_profile, default_profile, executable=None):
    """Résout un profil sélectionné ou le profil correspondant à l'application active."""
    profiles = normalize_profiles(profiles)
    if str(active_profile).casefold() != "automatique":
        selected = str(active_profile).casefold()
        for profile in profiles:
            if profile["name"].casefold() == selected:
                return profile
    else:
        executable = foreground_executable() if executable is None else executable.casefold()
        if executable:
            for profile in profiles:
                app = os.path.basename(profile["application"]).casefold()
                if app and app == executable:
                    return profile
    default_name = str(default_profile).casefold()
    for profile in profiles:
        if profile["name"].casefold() == default_name:
            return profile
    return profiles[0]


class ProfileDialog:
    """Éditeur local de profils et de leurs mappings clavier."""

    def __init__(self, parent, profiles, on_change):
        self.parent = parent
        self.profiles = copy.deepcopy(normalize_profiles(profiles))
        self.on_change = on_change
        self.editing_name = None
        self.loading = False
        self.window = tk.Toplevel(parent)
        self.window.title("Gestion des profils")
        self.window.geometry("680x610")
        self.window.minsize(620, 570)
        self.window.transient(parent)

        body = ttk.Frame(self.window, padding=10)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        ttk.Label(left, text="Profils").pack(anchor="w")
        self.listbox = tk.Listbox(left, width=22, exportselection=False)
        self.listbox.pack(fill="y", expand=True, pady=5)
        self.listbox.bind("<<ListboxSelect>>", self.select_profile)
        controls = ttk.Frame(left)
        controls.pack(fill="x")
        ttk.Button(controls, text="Nouveau", command=self.add_profile).pack(side="left")
        ttk.Button(controls, text="Supprimer", command=self.delete_profile).pack(side="left", padx=4)

        editor = ttk.Frame(body)
        editor.grid(row=0, column=1, sticky="nsew")
        editor.columnconfigure(1, weight=1)
        self.name_var = tk.StringVar()
        self.application_var = tk.StringVar()
        ttk.Label(editor, text="Nom du profil").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(editor, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(editor, text="Exécutable pour la sélection automatique").grid(
            row=1, column=0, sticky="w", pady=3)
        ttk.Entry(editor, textvariable=self.application_var).grid(
            row=1, column=1, sticky="ew", pady=3)
        ttk.Label(editor, text="Nom du fichier, par exemple Rouvy.exe").grid(
            row=2, column=1, sticky="w")

        self.action_vars = {}
        ttk.Label(editor, text="Événement", font=("Segoe UI", 9, "bold")).grid(
            row=3, column=0, sticky="w", pady=(12, 3))
        ttk.Label(editor, text="Touche clavier (vide = aucune action)",
                  font=("Segoe UI", 9, "bold")).grid(row=3, column=1, sticky="w", pady=(12, 3))
        for row, (key, label) in enumerate(ACTION_FIELDS, start=4):
            ttk.Label(editor, text=label).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar()
            self.action_vars[key] = var
            ttk.Entry(editor, textvariable=var, width=14).grid(row=row, column=1, sticky="w", pady=2)

        footer = ttk.Frame(body)
        footer.grid(row=1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(footer, text="Enregistrer le profil", command=self.save_profile).pack(side="left", padx=4)
        ttk.Button(footer, text="Terminé", command=self.close).pack(side="left")
        self.refresh_list()
        if self.profiles:
            self.listbox.selection_set(0)
            self.load_profile(0)
        self.window.grab_set()

    def refresh_list(self, selected=0):
        self.loading = True
        self.listbox.delete(0, "end")
        for profile in self.profiles:
            self.listbox.insert("end", profile["name"])
        self.loading = False
        if self.profiles:
            selected = max(0, min(selected, len(self.profiles) - 1))
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(selected)
            self.listbox.activate(selected)

    def select_profile(self, _event=None):
        if self.loading:
            return
        selection = self.listbox.curselection()
        if not selection:
            return
        if not self.save_profile(show_errors=False):
            self.refresh_list(self.current_index())
            return
        self.load_profile(selection[0])

    def current_index(self):
        selection = self.listbox.curselection()
        return selection[0] if selection else 0

    def load_profile(self, index):
        profile = self.profiles[index]
        self.editing_name = profile["name"]
        self.name_var.set(profile["name"])
        self.application_var.set(profile["application"])
        for key, var in self.action_vars.items():
            var.set(profile["actions"].get(key, ""))

    def save_profile(self, show_errors=True):
        if self.editing_name is None:
            return True
        name = self.name_var.get().strip()
        if not name:
            if show_errors:
                messagebox.showerror("Profil invalide", "Le nom du profil est obligatoire.", parent=self.window)
            return False
        for profile in self.profiles:
            if (profile["name"].casefold() == name.casefold() and
                    profile["name"].casefold() != self.editing_name.casefold()):
                if show_errors:
                    messagebox.showerror("Profil existant", "Ce nom de profil est déjà utilisé.", parent=self.window)
                return False
        index = next((i for i, p in enumerate(self.profiles)
                      if p["name"].casefold() == self.editing_name.casefold()), None)
        if index is None:
            return False
        self.profiles[index] = {
            "name": name,
            "application": self.application_var.get().strip(),
            "actions": {key: var.get().strip() for key, var in self.action_vars.items()
                        if var.get().strip()},
        }
        self.editing_name = name
        self.refresh_list(index)
        return True

    def add_profile(self):
        if not self.save_profile():
            return
        base, name, suffix = "Nouveau profil", "Nouveau profil", 2
        existing = {p["name"].casefold() for p in self.profiles}
        while name.casefold() in existing:
            name = f"{base} {suffix}"
            suffix += 1
        self.profiles.append({"name": name, "application": "", "actions": {}})
        index = len(self.profiles) - 1
        self.refresh_list(index)
        self.load_profile(index)

    def delete_profile(self):
        if len(self.profiles) <= 1:
            messagebox.showinfo("Profil nécessaire", "Il faut conserver au moins un profil.", parent=self.window)
            return
        index = self.current_index()
        del self.profiles[index]
        self.refresh_list(index)
        self.load_profile(min(index, len(self.profiles) - 1))

    def close(self):
        if not self.save_profile():
            return
        self.on_change(self.profiles)
        self.window.destroy()
