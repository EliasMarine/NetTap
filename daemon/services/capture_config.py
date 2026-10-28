"""
NetTap Capture Config — Read/write capture mode configuration.

Manages the INI-format config file that determines whether NetTap operates
in bridge mode (inline transparent tap) or mirror/SPAN mode (passive listener
on a switch port mirror).

Config file format (default: /etc/nettap/capture-mode.conf):

    [capture]
    mode = mirror
    interface = enp2s0
    management = enp3s0

    [bridge]
    wan_interface = enp2s0
    lan_interface = enp3s0

Falls back to environment variables if the config file doesn't exist,
defaulting to bridge mode for backwards compatibility.
"""

import configparser
import logging
import os
from dataclasses import dataclass, field

from services.capture_manager import CaptureMode

logger = logging.getLogger("nettap.services.capture_config")

DEFAULT_CONFIG_PATH = "/etc/nettap/capture-mode.conf"
DEFAULT_ENV_PATH = "/etc/nettap/capture.env"


@dataclass
class CaptureConfig:
    """Capture mode configuration."""

    mode: CaptureMode = CaptureMode.BRIDGE
    interface: str = "br0"  # mirror NIC name — used in mirror mode
    management: str = ""  # management NIC or WiFi — used in mirror mode
    wan_interface: str = "eth0"  # bridge WAN NIC — used in bridge mode
    lan_interface: str = "eth1"  # bridge LAN NIC — used in bridge mode
    bridge_name: str = "br0"  # bridge interface name


def _get_config_path(path: str | None = None) -> str:
    """Resolve the config file path from arg, env var, or default."""
    if path:
        return path
    return os.environ.get("CAPTURE_CONFIG_PATH", DEFAULT_CONFIG_PATH)


def _get_env_path(path: str | None = None) -> str:
    """Resolve the env file path from arg, env var, or default."""
    if path:
        return path
    return os.environ.get("CAPTURE_ENV_PATH", DEFAULT_ENV_PATH)


def load_capture_config(path: str | None = None) -> CaptureConfig:
    """Load capture configuration from INI file or environment variables.

    Resolution order:
        1. INI config file (if it exists)
        2. Environment variables (fallback)
        3. Defaults (bridge mode for backwards compatibility)

    Args:
        path: Optional explicit path to config file. If None, uses
              CAPTURE_CONFIG_PATH env var or /etc/nettap/capture-mode.conf.

    Returns:
        CaptureConfig with the resolved configuration.
    """
    config_path = _get_config_path(path)

    if os.path.exists(config_path):
        return _load_from_file(config_path)

    logger.info(
        "Config file %s not found, falling back to environment variables",
        config_path,
    )
    return _load_from_env()


def _load_from_file(config_path: str) -> CaptureConfig:
    """Parse capture config from an INI file."""
    parser = configparser.ConfigParser()
    parser.read(config_path)

    # Read [capture] section
    mode_str = parser.get("capture", "mode", fallback="bridge").strip().lower()
    try:
        mode = CaptureMode(mode_str)
    except ValueError:
        logger.warning(
            "Invalid capture mode '%s' in %s, defaulting to bridge",
            mode_str,
            config_path,
        )
        mode = CaptureMode.BRIDGE

    interface = parser.get("capture", "interface", fallback="br0").strip()
    management = parser.get("capture", "management", fallback="").strip()

    # Read [bridge] section
    wan_interface = parser.get("bridge", "wan_interface", fallback="eth0").strip()
    lan_interface = parser.get("bridge", "lan_interface", fallback="eth1").strip()

    config = CaptureConfig(
        mode=mode,
        interface=interface,
        management=management,
        wan_interface=wan_interface,
        lan_interface=lan_interface,
    )

    logger.info(
        "Loaded capture config from %s: mode=%s, interface=%s",
        config_path,
        config.mode.value,
        config.interface,
    )
    return config


def _load_from_env() -> CaptureConfig:
    """Build capture config from environment variables."""
    mode_str = os.environ.get("CAPTURE_MODE", "bridge").strip().lower()
    try:
        mode = CaptureMode(mode_str)
    except ValueError:
        logger.warning(
            "Invalid CAPTURE_MODE='%s', defaulting to bridge",
            mode_str,
        )
        mode = CaptureMode.BRIDGE

    config = CaptureConfig(
        mode=mode,
        interface=os.environ.get("PCAP_IFACE", "br0").strip(),
        management=os.environ.get("MANAGEMENT_IFACE", "").strip(),
        wan_interface=os.environ.get("WAN_IFACE", "eth0").strip(),
        lan_interface=os.environ.get("LAN_IFACE", "eth1").strip(),
    )

    logger.info(
        "Loaded capture config from environment: mode=%s, interface=%s",
        config.mode.value,
        config.interface,
    )
    return config


def save_capture_config(config: CaptureConfig, path: str | None = None) -> str:
    """Write capture configuration to an INI file.

    Creates parent directories if they don't exist.

    Args:
        config: The CaptureConfig to persist.
        path: Optional explicit path. If None, uses CAPTURE_CONFIG_PATH
              env var or /etc/nettap/capture-mode.conf.

    Returns:
        The path the config was written to.
    """
    config_path = _get_config_path(path)

    os.makedirs(os.path.dirname(config_path), exist_ok=True)

    parser = configparser.ConfigParser()

    parser.add_section("capture")
    parser.set("capture", "mode", config.mode.value)
    parser.set("capture", "interface", config.interface)
    parser.set("capture", "management", config.management)

    parser.add_section("bridge")
    parser.set("bridge", "wan_interface", config.wan_interface)
    parser.set("bridge", "lan_interface", config.lan_interface)

    with open(config_path, "w") as f:
        parser.write(f)

    logger.info(
        "Saved capture config to %s: mode=%s",
        config_path,
        config.mode.value,
    )
    return config_path


def write_env_file(config: CaptureConfig, path: str | None = None) -> str:
    """Write a .env file for docker-compose consumption.

    The env file contains the capture mode and the interface that capture
    tools (Zeek, Suricata, Arkime) should listen on. In bridge mode this
    is the bridge interface (br0); in mirror mode it's the mirror NIC.

    Args:
        config: The CaptureConfig to derive env values from.
        path: Optional explicit path. If None, uses CAPTURE_ENV_PATH
              env var or /etc/nettap/capture.env.

    Returns:
        The path the env file was written to.
    """
    env_path = _get_env_path(path)

    os.makedirs(os.path.dirname(env_path), exist_ok=True)

    # Determine the capture interface based on mode
    if config.mode == CaptureMode.MIRROR:
        pcap_iface = config.interface
    else:
        pcap_iface = config.bridge_name

    contents = (
        f"CAPTURE_MODE={config.mode.value}\n"
        f"PCAP_IFACE={pcap_iface}\n"
    )

    with open(env_path, "w") as f:
        f.write(contents)

    logger.info(
        "Wrote capture env file to %s: CAPTURE_MODE=%s, PCAP_IFACE=%s",
        env_path,
        config.mode.value,
        pcap_iface,
    )
    return env_path
