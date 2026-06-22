"""Application configuration and settings persistence."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

# Load API keys/secrets from .env next to this file (gitignored)
load_dotenv(Path(__file__).resolve().parent / ".env")

APP_NAME = "Music Manager"
APP_VERSION = "2.0.0"


CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "MusicManager"
CONFIG_FILE = CONFIG_DIR / "settings.json"
SECRETS_FILE = CONFIG_DIR / "secrets.json"
DB_FILE = CONFIG_DIR / "activity.db"
LOG_DIR = CONFIG_DIR / "logs"


def setup_logging() -> Path:
    """Send app logs to a rotating file in the config dir, at the configured
    level. Console output is left to uvicorn. Returns the log file path."""
    import logging
    from logging.handlers import RotatingFileHandler

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "app.log"
    level = getattr(logging, str(load_settings().get("log_level", "INFO")).upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        handler = RotatingFileHandler(log_file, maxBytes=1_000_000,
                                      backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    return log_file

# Which metadata providers REQUIRE an API key, and the secret name(s) each needs.
# Providers not listed here (MusicBrainz, Cover Art Archive, iTunes, Deezer) work
# with no key. AcoustID also needs the fpcalc binary, checked separately.
PROVIDER_KEYS = {
    "discogs": ["DISCOGS_TOKEN"],
    "lastfm": ["LASTFM_API_KEY"],
    "acoustid": ["ACOUSTID_API_KEY"],
    "fanarttv": ["FANARTTV_API_KEY"],
}


def load_secrets() -> dict:
    """User-entered API keys, persisted in the per-user config dir."""
    if SECRETS_FILE.exists():
        try:
            with open(SECRETS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def get_secret(name: str, default: str = "") -> str:
    """Read an API key/secret: environment (.env) wins, then the saved
    secrets file (entered via Settings)."""
    return os.environ.get(name) or load_secrets().get(name) or default


def save_secrets(updates: dict) -> None:
    """Merge key updates into the secrets file. An empty value clears that key."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    current = load_secrets()
    for name, value in updates.items():
        if value:
            current[name] = value
        else:
            current.pop(name, None)
    with open(SECRETS_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)


def provider_requires_key(provider: str) -> bool:
    return provider in PROVIDER_KEYS


def provider_has_keys(provider: str) -> bool:
    """True if a provider needs no key, or all its required keys are present."""
    return all(get_secret(n) for n in PROVIDER_KEYS.get(provider, []))

DEFAULT_SETTINGS = {
    "input_folder": "",
    "output_folder": "",
    "flac_exe_path": "",
    "compression_level": 8,
    "verify_encoding": True,
    "embed_album_art": True,
    "add_replay_gain": True,
    "fetch_performer_credits": True,
    "cross_provider_backfill": True,
    "art_max_size": 1200,
    "art_quality": 90,
    "plex_folder_format": "{artist}/{album} ({year})",
    "track_format": "{tracknumber:02d} - {title}",
    "multi_disc_style": "subfolder",
    "auto_lookup_metadata": True,
    "metadata_provider": "musicbrainz",  # "musicbrainz" or "discogs"
    "musicbrainz_user_agent": f"MusicManager/{APP_VERSION}",
    "discogs_token": "",
    "delete_wav_after_convert": False,
    "log_level": "INFO",
}


# Fields that contribute to a track's completeness score.
#
# Completeness measures whether a track is well-tagged for Plex — NOT whether
# it carries any one provider's internal IDs. With multi-source metadata
# (MusicBrainz, Discogs, Last.fm, iTunes…), requiring MusicBrainz-specific
# artist IDs wrongly caps fully-tagged albums below 100%.
PLEX_DISPLAY_FIELDS = [
    "TITLE", "ARTIST", "ALBUMARTIST", "ALBUM",
    "TRACKNUMBER", "DISCNUMBER", "DATE", "GENRE",
]
PLEX_OPTIONAL_FIELDS = [
    "TRACKTOTAL", "DISCTOTAL",
]
# A single, source-agnostic "is this track matchable?" credit: satisfied when
# ANY of these external identifiers is present (any provider counts).
PLEX_IDENTIFIER_FIELDS = [
    "MUSICBRAINZ_ALBUMID", "MUSICBRAINZ_RELEASEGROUPID", "MUSICBRAINZ_TRACKID",
    "DISCOGS_ALBUMID", "DISCOGS_RELEASEID",
]

# Scored slots: each display + each optional + cover art + one identifier credit
PLEX_SCORED_SLOTS = len(PLEX_DISPLAY_FIELDS) + len(PLEX_OPTIONAL_FIELDS) + 2

# Backwards-compat alias (older references expect a flat field list)
PLEX_ALL_FIELDS = PLEX_DISPLAY_FIELDS + PLEX_OPTIONAL_FIELDS


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    ensure_config_dir()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        merged = {**DEFAULT_SETTINGS, **saved}
        return merged
    return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict):
    ensure_config_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
