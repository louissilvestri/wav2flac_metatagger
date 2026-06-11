"""Application configuration and settings persistence."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

# Load API keys/secrets from .env next to this file (gitignored)
load_dotenv(Path(__file__).resolve().parent / ".env")

APP_NAME = "Music Manager"
APP_VERSION = "2.0.0-dev"


def get_secret(name: str, default: str = "") -> str:
    """Read an API key/secret from the environment (.env)."""
    return os.environ.get(name, default)
CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "MusicManager"
CONFIG_FILE = CONFIG_DIR / "settings.json"
DB_FILE = CONFIG_DIR / "activity.db"

DEFAULT_SETTINGS = {
    "input_folder": "",
    "output_folder": "",
    "flac_exe_path": "",
    "compression_level": 8,
    "verify_encoding": True,
    "embed_album_art": True,
    "art_max_size": 1200,
    "art_quality": 90,
    "plex_folder_format": "{artist}/{album} ({year})",
    "track_format": "{tracknumber:02d} - {title}",
    "multi_disc_style": "subfolder",
    "auto_lookup_metadata": True,
    "metadata_provider": "musicbrainz",  # "musicbrainz" or "discogs"
    "musicbrainz_user_agent": f"MusicManager/{APP_VERSION} (louissilvestri@hotmail.com)",
    "discogs_token": "",
    "delete_wav_after_convert": False,
    "log_level": "INFO",
}


# Plex-supported Vorbis Comment fields for completeness scoring
PLEX_DISPLAY_FIELDS = [
    "TITLE", "ARTIST", "ALBUMARTIST", "ALBUM",
    "TRACKNUMBER", "DISCNUMBER", "DATE", "GENRE",
]
PLEX_MATCH_FIELDS = [
    "MUSICBRAINZ_ALBUMID", "MUSICBRAINZ_ARTISTID",
    "MUSICBRAINZ_TRACKID", "MUSICBRAINZ_ALBUMARTISTID",
]
PLEX_OPTIONAL_FIELDS = [
    "TRACKTOTAL", "DISCTOTAL",
]
PLEX_ALL_FIELDS = PLEX_DISPLAY_FIELDS + PLEX_MATCH_FIELDS + PLEX_OPTIONAL_FIELDS


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
