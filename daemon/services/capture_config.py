"""
NetTap Capture Config — Read/write capture mode configuration.

Manages the INI-format config file that determines whether NetTap operates
in DHCP gateway mode (NetTap serves its own subnet and routes to the router),
mirror/SPAN mode (passive listener on a switch port mirror) or bridge mode
(inline transparent tap).

Config file format (default: /etc/nettap/capture-mode.conf):

    [capture]
    mode = mirror
    interface = enp2s0
    management = enp3s0

    [bridge]
    wan_interface = enp2s0
    lan_interface = enp3s0

    [dhcp_gateway]
    subnet = 10.77.0.0/24
    upstream_address = 192.168.1.50/24
    upstream_gateway = 192.168.1.1
    dhcp_enabled = false

A missing [dhcp_gateway] section loads as the defaults, so older files still
load. Both files are written atomically (temp file + rename), because the
capture containers and the boot path read them.

Falls back to environment variables if the config file doesn't exist,
defaulting to bridge mode for backwards compatibility.
"""

import configparser
import contextlib
import io
import logging
import os
import tempfile
from dataclasses import dataclass

from services.capture_manager import CaptureMode
from services.dhcp_gateway_net import capture_filter, validate_interface_name

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
    dhcp_subnet: str = "10.77.0.0/24"  # subnet NetTap serves in DHCP gateway mode
    dhcp_upstream_address: str = ""  # NetTap's router-side CIDR, set by enable
    dhcp_upstream_gateway: str = ""  # the router's IP, set by enable
    dhcp_enabled: bool = False  # DHCP server on/off (routing stays on when off)


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
    # ";" inline comments as in the design doc example; no value contains ";"
    parser = configparser.ConfigParser(inline_comment_prefixes=(";",))
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

    # Read [dhcp_gateway] section (values are validated where they are used)
    defaults = CaptureConfig()
    try:
        dhcp_enabled = parser.getboolean(
            "dhcp_gateway", "dhcp_enabled", fallback=defaults.dhcp_enabled
        )
    except ValueError:
        # Off is the safe reading: a second DHCP server is worse than none
        logger.warning(
            "Invalid dhcp_enabled value in %s, treating it as false", config_path
        )
        dhcp_enabled = False

    config = CaptureConfig(
        mode=mode,
        interface=interface,
        management=management,
        wan_interface=wan_interface,
        lan_interface=lan_interface,
        dhcp_subnet=parser.get(
            "dhcp_gateway", "subnet", fallback=defaults.dhcp_subnet
        ).strip(),
        dhcp_upstream_address=parser.get(
            "dhcp_gateway", "upstream_address", fallback=""
        ).strip(),
        dhcp_upstream_gateway=parser.get(
            "dhcp_gateway", "upstream_gateway", fallback=""
        ).strip(),
        dhcp_enabled=dhcp_enabled,
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


def write_file_atomic(path: str, text: str, mode: int = 0o644) -> None:
    """Write ``text`` to ``path`` via a temp file in the same dir and os.replace.

    Readers see either the old file or the new one, never a partial write.
    """
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(path) or ".", prefix=f".{os.path.basename(path)}."
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def save_capture_config(config: CaptureConfig, path: str | None = None) -> str:
    """Write capture configuration to an INI file (atomically).

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

    parser.add_section("dhcp_gateway")
    parser.set("dhcp_gateway", "subnet", config.dhcp_subnet)
    parser.set("dhcp_gateway", "upstream_address", config.dhcp_upstream_address)
    parser.set("dhcp_gateway", "upstream_gateway", config.dhcp_upstream_gateway)
    parser.set("dhcp_gateway", "dhcp_enabled", str(config.dhcp_enabled).lower())

    # OLD CODE START — replaced 2026-10-30: a plain write could leave a
    # half-written file for the capture containers / boot path to read
    # with open(config_path, "w") as f:
    #     parser.write(f)
    # OLD CODE END
    buf = io.StringIO()
    parser.write(buf)
    write_file_atomic(config_path, buf.getvalue())

    logger.info(
        "Saved capture config to %s: mode=%s",
        config_path,
        config.mode.value,
    )
    return config_path


def write_env_file(config: CaptureConfig, path: str | None = None) -> str:
    """Write a .env file for docker-compose consumption.

    The env file contains the capture mode, the interface that capture
    tools (Zeek, Suricata, Arkime) should listen on, and the BPF filter.
    In bridge mode the interface is the bridge (br0); in mirror and DHCP
    gateway mode it's the configured NIC. Only DHCP gateway mode sets a
    filter (the device leg of the subnet plus DHCP); the others leave it empty.

    The file is written atomically. Raises ValueError if the interface name
    or the DHCP subnet is invalid, so nothing unsafe is ever written.

    Args:
        config: The CaptureConfig to derive env values from.
        path: Optional explicit path. If None, uses CAPTURE_ENV_PATH
              env var or /etc/nettap/capture.env.

    Returns:
        The path the env file was written to.
    """
    env_path = _get_env_path(path)

    os.makedirs(os.path.dirname(env_path), exist_ok=True)

    # Determine the capture interface and filter based on mode
    pcap_filter = ""
    if config.mode in (CaptureMode.MIRROR, CaptureMode.DHCP_GATEWAY):
        pcap_iface = config.interface
    else:
        pcap_iface = config.bridge_name
    if config.mode == CaptureMode.DHCP_GATEWAY:
        pcap_filter = capture_filter(config.dhcp_subnet)
    validate_interface_name(pcap_iface)

    contents = (
        f"CAPTURE_MODE={config.mode.value}\n"
        f"PCAP_IFACE={pcap_iface}\n"
        f"PCAP_FILTER={pcap_filter}\n"
    )

    # OLD CODE START — replaced 2026-10-30: a plain write could leave a
    # half-written file for the capture containers to read on restart
    # with open(env_path, "w") as f:
    #     f.write(contents)
    # OLD CODE END
    write_file_atomic(env_path, contents)

    logger.info(
        "Wrote capture env file to %s: CAPTURE_MODE=%s, PCAP_IFACE=%s, PCAP_FILTER=%s",
        env_path,
        config.mode.value,
        pcap_iface,
        pcap_filter or "(none)",
    )
    return env_path


def write_env_file_if_changed(
    config: CaptureConfig, path: str | None = None
) -> tuple[str, bool]:
    """Write capture.env like write_env_file; returns (path, whether it changed).

    Callers restart the capture containers only when the content changed.
    """
    try:
        with open(_get_env_path(path), "r") as f:
            before = f.read()
    except FileNotFoundError:
        before = None
    written = write_env_file(config, path)
    with open(written, "r") as f:
        return written, f.read() != before
