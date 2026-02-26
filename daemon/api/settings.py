"""
NetTap Settings API Routes

Registers REST endpoints for managing API keys and configuration settings.
Keys are stored in the environment file and exposed only as boolean
"configured" flags — never as raw values — to prevent accidental leakage.

Endpoints:
    GET  /api/settings/api-keys   Check which API keys are configured
    POST /api/settings/api-keys   Save API key values to env file
"""

import logging
import os
from pathlib import Path

from aiohttp import web

logger = logging.getLogger("nettap.api.settings")

# The env file that stores API key values
DEFAULT_ENV_FILE = "/opt/nettap/.env"

# All known API key fields and their env variable names
API_KEY_FIELDS = {
    "MAXMIND_LICENSE_KEY": "MAXMIND_LICENSE_KEY",
    "SMTP_HOST": "SMTP_HOST",
    "SMTP_PORT": "SMTP_PORT",
    "SMTP_USERNAME": "SMTP_USERNAME",
    "SMTP_PASSWORD": "SMTP_PASSWORD",
    "SMTP_SENDER_EMAIL": "SMTP_SENDER_EMAIL",
    "WEBHOOK_URL": "WEBHOOK_URL",
    "SURICATA_ET_PRO_KEY": "SURICATA_ET_PRO_KEY",
}


def _get_env_file(app: web.Application) -> str:
    """Get the env file path from app config or default."""
    return app.get("env_file", DEFAULT_ENV_FILE)


def _load_env_file(env_file: str) -> dict[str, str]:
    """Load key-value pairs from an env file.

    Parses lines of the form KEY=VALUE. Lines starting with # or
    empty lines are skipped. Values may optionally be quoted.
    """
    env_vars: dict[str, str] = {}
    path = Path(env_file)
    if not path.exists():
        return env_vars

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes if present
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        env_vars[key] = value

    return env_vars


def _save_env_file(env_file: str, updates: dict[str, str]) -> None:
    """Merge updates into the env file, preserving existing entries.

    Existing keys are updated in-place; new keys are appended.
    Comments and blank lines are preserved.
    """
    path = Path(env_file)

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    existing_lines: list[str] = []
    if path.exists():
        existing_lines = path.read_text().splitlines()

    updated_keys: set[str] = set()
    new_lines: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in updates:
                value = updates[key]
                new_lines.append(f'{key}="{value}"')
                updated_keys.add(key)
                continue
        new_lines.append(line)

    # Append any new keys that weren't already in the file
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f'{key}="{value}"')

    path.write_text("\n".join(new_lines) + "\n")


def _check_configured(env_vars: dict[str, str]) -> dict[str, bool]:
    """Return a dict indicating which API keys are configured (non-empty)."""
    result: dict[str, bool] = {}
    for field_name, env_name in API_KEY_FIELDS.items():
        value = env_vars.get(env_name, "") or os.environ.get(env_name, "")
        result[field_name] = bool(value.strip())
    return result


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def handle_get_api_keys(request: web.Request) -> web.Response:
    """GET /api/settings/api-keys

    Returns which API keys are configured (boolean flags only).
    Never returns actual key values.
    """
    env_file = _get_env_file(request.app)
    env_vars = _load_env_file(env_file)
    configured = _check_configured(env_vars)
    return web.json_response({"keys": configured})


async def handle_save_api_keys(request: web.Request) -> web.Response:
    """POST /api/settings/api-keys

    Save API key values to the env file. Accepts a JSON body with
    key-value pairs. Only known API key fields are accepted.

    Body: { "MAXMIND_LICENSE_KEY": "abc123", "SMTP_HOST": "smtp.example.com", ... }
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be a JSON object"}, status=400)

    # Filter to only known fields
    updates: dict[str, str] = {}
    unknown_keys: list[str] = []
    for key, value in body.items():
        if key in API_KEY_FIELDS:
            updates[key] = str(value) if value is not None else ""
        else:
            unknown_keys.append(key)

    if not updates:
        return web.json_response(
            {"error": "No valid API key fields provided"},
            status=400,
        )

    env_file = _get_env_file(request.app)

    try:
        _save_env_file(env_file, updates)
    except Exception as exc:
        logger.exception("Failed to save API keys to %s", env_file)
        return web.json_response(
            {"error": f"Failed to save API keys: {exc}"},
            status=500,
        )

    # Re-read to confirm what's now configured
    env_vars = _load_env_file(env_file)
    configured = _check_configured(env_vars)

    response: dict = {
        "result": "saved",
        "keys": configured,
        "saved_count": len(updates),
    }
    if unknown_keys:
        response["warnings"] = [f"Unknown key ignored: {k}" for k in unknown_keys]

    return web.json_response(response)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_settings_routes(app: web.Application, env_file: str | None = None) -> None:
    """Register settings API routes on the aiohttp application.

    Args:
        app: The aiohttp web application to register routes on.
        env_file: Optional path to the env file. Defaults to /opt/nettap/.env.
    """
    if env_file:
        app["env_file"] = env_file
    else:
        app["env_file"] = os.environ.get("NETTAP_ENV_FILE", DEFAULT_ENV_FILE)

    app.router.add_get("/api/settings/api-keys", handle_get_api_keys)
    app.router.add_post("/api/settings/api-keys", handle_save_api_keys)

    logger.info("Settings API routes registered")
