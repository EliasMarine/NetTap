"""
Home location store for NetTap.

Where the network is, set by the user in Settings › Network location: the Live
page's globe flies packets between this point and each destination. One small
JSON file on the daemon's data volume, so every browser sees the same place.
"""

import json
import logging
import os
import tempfile
import unicodedata

logger = logging.getLogger("nettap.services.home_location")

DEFAULT_HOME_LOCATION_FILE = "/opt/nettap/data/home_location.json"
MAX_LABEL = 80


def _get_file_path() -> str:
    return os.environ.get("HOME_LOCATION_FILE", DEFAULT_HOME_LOCATION_FILE)


def _coordinate(value, name: str, limit: float) -> float:
    # bool is an int in Python; a JSON true must not read as 1°
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{name}' must be a number")
    # A comparison, not math.isfinite: NaN fails it, and a huge JSON int never becomes a float
    if not -limit <= value <= limit:
        raise ValueError(f"'{name}' must be between -{limit:g} and {limit:g}")
    return round(float(value), 4)


def parse_home(body) -> dict:
    """{lat, lon, label} from untrusted JSON, or ValueError with a message for the user."""
    if not isinstance(body, dict):
        raise ValueError("Body must be a JSON object with 'lat' and 'lon'")
    label = body.get("label")
    if label is None:
        label = ""
    if not isinstance(label, str):
        raise ValueError("'label' must be text")
    label = label.strip()
    if len(label) > MAX_LABEL:
        raise ValueError(f"'label' must be at most {MAX_LABEL} characters")
    if any(unicodedata.category(ch).startswith("C") for ch in label):
        raise ValueError("'label' must not contain control characters")
    return {
        "lat": _coordinate(body.get("lat"), "lat", 90),
        "lon": _coordinate(body.get("lon"), "lon", 180),
        "label": label,
    }


def load_home(file_path: str | None = None) -> dict | None:
    """The saved location, or None: never saved, or a file that no longer parses (logged)."""
    path = file_path or _get_file_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return parse_home(json.load(f))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:  # JSONDecodeError is a ValueError
        logger.warning("Ignoring the home location file %s: %s", path, exc)
        return None


def save_home(home: dict, file_path: str | None = None) -> None:
    """Write atomically, so a crash mid-write never leaves half a file."""
    path = file_path or _get_file_path()
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".home_location.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(home, f)
            f.flush()
            os.fsync(
                f.fileno()
            )  # on disk before the rename, so a power cut never leaves it empty
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    logger.info("Saved the home location")


def clear_home(file_path: str | None = None) -> None:
    path = file_path or _get_file_path()
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    logger.info("Cleared the home location")
