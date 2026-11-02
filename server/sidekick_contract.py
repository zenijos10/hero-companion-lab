"""Where the Sidekick ID map ("contract") comes from: one swappable provider list.

The importer only ever asks `locate_contract(providers)` for a folder in the
Sidekick contract layout (manifest.json, powersets/..., archetypes.json,
boost-index.json, enhancements.json, mids-names.json). Every provider is one
small class with `name` and `locate()`; one that can fetch its data also has
`install()`.

Pivoting if CoH Sidekick ever stops: point SIDEKICK_SNAPSHOT at another copy
of the same bundle (url + sha256), or add a provider that writes the same
layout from somewhere else. Nothing downstream of locate_contract changes.
"""
import gzip
import hashlib
import io
import json
import os
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path


MAX_DOWNLOAD_BYTES = 20_000_000
_MAX_UNPACKED_BYTES = 200_000_000


@dataclass(frozen=True)
class Snapshot:
    """One exact, verifiable copy of Sidekick's Homecoming data bundle."""
    version: str
    url: str
    sha256: str
    size_bytes: int = 0
    max_bytes: int = MAX_DOWNLOAD_BYTES


# CoH Sidekick (AGPL-3.0, github.com/wednesdaywoe/coh-sidekick) publishes this
# bundle; the same commit is pinned in CI. Only these exact bytes install.
SIDEKICK_SNAPSHOT = Snapshot(
    version="90e9b8eeaf59a2350e62587968f523a1e1371f88",
    url=("https://raw.githubusercontent.com/wednesdaywoe/coh-sidekick/"
         "90e9b8eeaf59a2350e62587968f523a1e1371f88/contract/homecoming/bundle.json.gz"),
    sha256="d2d336aac9c76a83d139ad4db4c99d649454ebddb1a8006c1bcb1ef45c205376",
    size_bytes=2_404_025,
)


class ContractUnavailable(Exception):
    """The ID map could not be obtained; nothing was installed."""


class ConfiguredFolder:
    """A contract folder the person running the app pointed at themselves."""
    name = "configured-folder"

    def __init__(self, environ=None):
        self._environ = os.environ if environ is None else environ

    def locate(self):
        folder = (self._environ.get("HC_SIDEKICK_CONTRACT_DIR") or "").strip()
        return Path(folder) if folder and os.path.isdir(folder) else None


class DownloadedSnapshot:
    """A pinned Sidekick bundle, fetched once with consent and cached locally."""
    name = "sidekick-download"

    def __init__(self, cache_root, snapshot, fetch=None):
        self._cache_root = Path(cache_root)
        self.snapshot = snapshot
        self._fetch = fetch or _https_fetch

    @property
    def _target(self):
        return self._cache_root / self.snapshot.version

    def locate(self):
        return self._target if (self._target / "manifest.json").is_file() else None

    def install(self):
        """Fetch, verify and unpack; the folder appears whole or not at all."""
        ready = self.locate()
        if ready:
            return ready
        raw = self._fetch(self.snapshot.url, self.snapshot.max_bytes)
        if len(raw) > self.snapshot.max_bytes:
            raise ContractUnavailable("Sidekick data download is larger than expected.")
        if hashlib.sha256(raw).hexdigest() != self.snapshot.sha256:
            raise ContractUnavailable("Sidekick data did not match the pinned version.")
        bundle = _read_bundle(raw)
        self._cache_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=self._cache_root))
        try:
            write_contract_from_bundle(bundle, staging)
            os.replace(staging, self._target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return self._target


def locate_contract(providers):
    """Return (folder, provider name) from the first provider that has one."""
    for provider in providers:
        folder = provider.locate()
        if folder:
            return folder, provider.name
    return None, None


def installer(providers):
    """The first provider able to fetch its data, or None."""
    return next((p for p in providers if callable(getattr(p, "install", None))), None)


def default_providers(cache_root):
    return [ConfiguredFolder(), DownloadedSnapshot(cache_root, SIDEKICK_SNAPSHOT)]


def write_contract_from_bundle(bundle, target):
    """Write the slim contract layout the importer reads from a parsed bundle."""
    target = Path(target).resolve()
    manifest = bundle.get("manifest")
    powersets = bundle.get("powersets")
    if not isinstance(manifest, dict) or manifest.get("dataset") != "homecoming":
        raise ContractUnavailable("Sidekick data is not the Homecoming dataset.")
    if not isinstance(manifest.get("shards"), list) or not isinstance(powersets, dict):
        raise ContractUnavailable("Sidekick data is missing its powerset index.")
    for entry in manifest["shards"]:
        _write_shard(entry, powersets, target)
    _write_json(target / "manifest.json", {"dataset": manifest["dataset"],
                                           "shards": manifest["shards"]})
    for name in ("archetypes", "boost-index", "enhancements", "mids-names"):
        if not isinstance(bundle.get(name), dict):
            raise ContractUnavailable(f"Sidekick data is missing {name}.")
        _write_json(target / f"{name}.json", bundle[name])


def _write_shard(entry, powersets, target):
    shard_id = entry.get("id") if isinstance(entry, dict) else None
    shard = powersets.get(shard_id)
    path = entry.get("path") if isinstance(entry, dict) else None
    if not isinstance(shard, dict) or not isinstance(path, str) or not path:
        raise ContractUnavailable(f"Sidekick powerset {shard_id!r} is missing.")
    destination = (target / path).resolve()
    if not destination.is_relative_to(target) or destination == target:
        raise ContractUnavailable(f"Sidekick powerset {shard_id!r} has an unsafe path.")
    _write_json(destination, {
        "id": shard.get("id"), "setPath": shard.get("setPath"),
        "archetype": shard.get("archetype"), "category": shard.get("category"),
        "powers": [{"internalName": p.get("internalName")}
                   for p in shard.get("powers") or [] if isinstance(p, dict)],
    })


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _read_bundle(raw):
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            text = stream.read(_MAX_UNPACKED_BYTES + 1)
        if len(text) > _MAX_UNPACKED_BYTES:
            raise ContractUnavailable("Sidekick data unpacks larger than expected.")
        bundle = json.loads(text.decode("utf-8"))
    except (OSError, EOFError, ValueError) as exc:
        raise ContractUnavailable(f"Sidekick data could not be read: {exc}") from exc
    if not isinstance(bundle, dict):
        raise ContractUnavailable("Sidekick data has an unexpected shape.")
    return bundle



def _https_fetch(url, max_bytes):
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.read(max_bytes + 1)
    except OSError as exc:
        raise ContractUnavailable(f"Could not download Sidekick data: {exc}") from exc
