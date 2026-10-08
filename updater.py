"""Vérification GitHub Releases et téléchargement vérifié de l'installateur."""
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request


OWNER = "TBrassart"
REPOSITORY = "ClickBridge"
API_LATEST = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{OWNER}/{REPOSITORY}/releases/latest"
INSTALLER_NAME = "ClickBridge-Setup.exe"
CHECKSUMS_NAME = "SHA256SUMS.txt"
MAX_INSTALLER_BYTES = 250 * 1024 * 1024
VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


class UpdateError(RuntimeError):
    pass


def _version_tuple(value):
    match = VERSION_PATTERN.fullmatch(str(value).strip())
    if not match:
        raise UpdateError(f"Version de release non reconnue : {value!r}")
    return tuple(int(part) for part in match.groups())


def _github_request(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": "ClickBridge-Update-Checker",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and url == API_LATEST:
            return None
        raise UpdateError(f"GitHub a répondu HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Connexion à GitHub impossible : {exc}") from exc


def _asset(release, name):
    assets = release.get("assets", [])
    return next((asset for asset in assets if asset.get("name") == name), None)


def check_for_update(current_version):
    """Retourne release status, release metadata et téléchargement vérifiable."""
    payload = _github_request(API_LATEST)
    if payload is None:
        return {"status": "no_release", "current_version": current_version,
                "release_url": RELEASES_PAGE}
    try:
        release = json.loads(payload.decode("utf-8"))
        tag = str(release["tag_name"])
        latest_tuple = _version_tuple(tag)
        current_tuple = _version_tuple(current_version)
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise UpdateError("La réponse de release GitHub est invalide.") from exc
    latest_version = tag.removeprefix("v")
    result = {
        "status": "available" if latest_tuple > current_tuple else "current",
        "current_version": current_version,
        "latest_version": latest_version,
        "release_url": release.get("html_url", RELEASES_PAGE),
        "release_notes": str(release.get("body") or "")[:8000],
        "installer": None,
        "checksums": None,
    }
    release_page = urllib.parse.urlparse(str(result["release_url"]))
    if release_page.scheme != "https" or release_page.hostname != "github.com":
        raise UpdateError("GitHub a fourni une URL de release non sécurisée.")
    installer = _asset(release, INSTALLER_NAME)
    checksums = _asset(release, CHECKSUMS_NAME)
    if installer and checksums:
        for item in (installer, checksums):
            parsed = urllib.parse.urlparse(str(item.get("browser_download_url", "")))
            if parsed.scheme != "https" or parsed.hostname not in ("github.com", "objects.githubusercontent.com"):
                raise UpdateError("GitHub a fourni une URL d'asset non sécurisée.")
        result["installer"] = {
            "url": installer["browser_download_url"],
            "size": installer.get("size", 0),
            "digest": installer.get("digest"),
        }
        result["checksums"] = {"url": checksums["browser_download_url"]}
    return result


def _download(url, destination, maximum=MAX_INSTALLER_BYTES):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ("github.com", "objects.githubusercontent.com"):
        raise UpdateError("URL de téléchargement refusée.")
    request = urllib.request.Request(url, headers={"User-Agent": "ClickBridge-Update-Checker"})
    digest = hashlib.sha256()
    received = 0
    try:
        with urllib.request.urlopen(request, timeout=45) as response, open(destination, "wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > maximum:
                    raise UpdateError("L'asset dépasse la taille autorisée.")
                digest.update(chunk)
                output.write(chunk)
    except UpdateError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Téléchargement impossible : {exc}") from exc
    if received == 0:
        raise UpdateError("GitHub a renvoyé un fichier vide.")
    return digest.hexdigest(), received


def download_verified_installer(update, destination_dir):
    """Télécharge l'installateur, exige et vérifie son empreinte SHA-256."""
    installer = update.get("installer")
    checksums = update.get("checksums")
    if not installer or not checksums:
        raise UpdateError("Cette release ne contient pas l'installateur et son fichier SHA256SUMS.")
    os.makedirs(destination_dir, exist_ok=True)
    fd, checksum_path = tempfile.mkstemp(prefix="clickbridge-checksums-", suffix=".tmp",
                                         dir=destination_dir)
    os.close(fd)
    fd, partial_path = tempfile.mkstemp(prefix="clickbridge-update-", suffix=".part",
                                        dir=destination_dir)
    os.close(fd)
    final_path = os.path.join(destination_dir,
                              f"ClickBridge-Setup-{update['latest_version']}.exe")
    try:
        _download(checksums["url"], checksum_path, maximum=1024 * 1024)
        with open(checksum_path, encoding="utf-8-sig") as stream:
            checksum_text = stream.read()
        expected = None
        for line in checksum_text.splitlines():
            match = re.fullmatch(r"\s*([0-9a-fA-F]{64})\s+\*?ClickBridge-Setup\.exe\s*", line)
            if match:
                expected = match.group(1).lower()
                break
        if not expected:
            raise UpdateError("SHA256SUMS.txt ne contient pas l'empreinte de l'installateur.")
        actual, size = _download(installer["url"], partial_path)
        if actual != expected:
            raise UpdateError("La vérification SHA-256 de l'installateur a échoué.")
        api_digest = installer.get("digest")
        if api_digest and str(api_digest).lower() != f"sha256:{actual}":
            raise UpdateError("L'empreinte de l'asset annoncée par GitHub ne correspond pas.")
        declared_size = installer.get("size")
        if isinstance(declared_size, int) and declared_size > 0 and declared_size != size:
            raise UpdateError("La taille téléchargée ne correspond pas à la taille publiée.")
        os.replace(partial_path, final_path)
        return final_path
    finally:
        for temporary in (checksum_path, partial_path):
            try:
                os.remove(temporary)
            except OSError:
                pass
