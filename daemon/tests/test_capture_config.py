"""
Tests for daemon/services/capture_config.py

Tests cover config loading from INI files, environment variables, defaults,
save/load roundtrips, .env file generation for docker-compose, the
[dhcp_gateway] section, PCAP_FILTER, and atomic writes.
Uses tmp_path fixture for temp files — no real /etc/nettap access required.
"""

import os
import stat
import sys

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch

from services import capture_config
from services.capture_config import (
    CaptureConfig,
    load_capture_config,
    save_capture_config,
    write_env_file,
    write_file_atomic,
)
from services.capture_manager import CaptureMode


class TestLoadFromFile:
    """Tests for loading config from an INI file."""

    def test_load_from_file(self, tmp_path):
        """Load a valid INI config file and verify all fields."""
        config_file = tmp_path / "capture-mode.conf"
        config_file.write_text(
            "[capture]\n"
            "mode = mirror\n"
            "interface = enp2s0\n"
            "management = enp3s0\n"
            "\n"
            "[bridge]\n"
            "wan_interface = enp4s0\n"
            "lan_interface = enp5s0\n"
        )

        config = load_capture_config(path=str(config_file))

        assert config.mode == CaptureMode.MIRROR
        assert config.interface == "enp2s0"
        assert config.management == "enp3s0"
        assert config.wan_interface == "enp4s0"
        assert config.lan_interface == "enp5s0"

    def test_load_bridge_mode_from_file(self, tmp_path):
        """Load a bridge-mode INI config file."""
        config_file = tmp_path / "capture-mode.conf"
        config_file.write_text(
            "[capture]\n"
            "mode = bridge\n"
            "interface = br0\n"
            "\n"
            "[bridge]\n"
            "wan_interface = enp2s0\n"
            "lan_interface = enp3s0\n"
        )

        config = load_capture_config(path=str(config_file))

        assert config.mode == CaptureMode.BRIDGE
        assert config.interface == "br0"
        assert config.wan_interface == "enp2s0"
        assert config.lan_interface == "enp3s0"


class TestLoadFromEnvVars:
    """Tests for loading config from environment variables."""

    def test_load_from_env_vars(self, tmp_path):
        """Set env vars and verify config loaded from them."""
        # Point to a non-existent file so env fallback is used
        fake_path = str(tmp_path / "nonexistent.conf")

        env = {
            "CAPTURE_MODE": "mirror",
            "PCAP_IFACE": "eth5",
            "MANAGEMENT_IFACE": "wlan0",
            "WAN_IFACE": "enp2s0",
            "LAN_IFACE": "enp3s0",
        }
        with patch.dict(os.environ, env, clear=False):
            config = load_capture_config(path=fake_path)

        assert config.mode == CaptureMode.MIRROR
        assert config.interface == "eth5"
        assert config.management == "wlan0"
        assert config.wan_interface == "enp2s0"
        assert config.lan_interface == "enp3s0"


class TestLoadDefaults:
    """Tests for default configuration values."""

    def test_load_defaults_to_bridge(self, tmp_path):
        """No config file and no env vars should default to bridge mode."""
        fake_path = str(tmp_path / "nonexistent.conf")

        # Clear capture-related env vars
        env_to_clear = {
            "CAPTURE_MODE": "",
            "PCAP_IFACE": "",
            "MANAGEMENT_IFACE": "",
            "WAN_IFACE": "",
            "LAN_IFACE": "",
        }
        # Remove the vars entirely by patching with empty and relying on .get defaults
        with patch.dict(os.environ, {}, clear=False):
            # Remove any existing capture env vars
            for key in env_to_clear:
                os.environ.pop(key, None)
            config = load_capture_config(path=fake_path)

        assert config.mode == CaptureMode.BRIDGE
        assert config.interface == "br0"
        assert config.wan_interface == "eth0"
        assert config.lan_interface == "eth1"


class TestSaveAndLoadRoundtrip:
    """Tests for save/load roundtrip."""

    def test_save_and_load_roundtrip(self, tmp_path):
        """Save config, load it back, and verify all fields match."""
        config_file = str(tmp_path / "capture-mode.conf")

        original = CaptureConfig(
            mode=CaptureMode.MIRROR,
            interface="enp2s0",
            management="wlan0",
            wan_interface="enp4s0",
            lan_interface="enp5s0",
            bridge_name="br0",
        )

        save_capture_config(original, path=config_file)
        loaded = load_capture_config(path=config_file)

        assert loaded.mode == original.mode
        assert loaded.interface == original.interface
        assert loaded.management == original.management
        assert loaded.wan_interface == original.wan_interface
        assert loaded.lan_interface == original.lan_interface

    def test_save_bridge_roundtrip(self, tmp_path):
        """Save and reload a bridge-mode config."""
        config_file = str(tmp_path / "capture-mode.conf")

        original = CaptureConfig(
            mode=CaptureMode.BRIDGE,
            interface="br0",
            management="",
            wan_interface="enp2s0",
            lan_interface="enp3s0",
        )

        save_capture_config(original, path=config_file)
        loaded = load_capture_config(path=config_file)

        assert loaded.mode == CaptureMode.BRIDGE
        assert loaded.wan_interface == "enp2s0"
        assert loaded.lan_interface == "enp3s0"


class TestWriteEnvFile:
    """Tests for write_env_file() — docker-compose .env generation."""

    def test_write_env_file(self, tmp_path):
        """Write env file, read it back, verify CAPTURE_MODE and PCAP_IFACE."""
        env_file = str(tmp_path / "capture.env")

        config = CaptureConfig(
            mode=CaptureMode.MIRROR,
            interface="enp2s0",
        )

        write_env_file(config, path=env_file)

        contents = open(env_file).read()
        assert "CAPTURE_MODE=mirror" in contents
        assert "PCAP_IFACE=enp2s0" in contents

    def test_mirror_mode_env_file(self, tmp_path):
        """In mirror mode, PCAP_IFACE should be the mirror interface."""
        env_file = str(tmp_path / "capture.env")

        config = CaptureConfig(
            mode=CaptureMode.MIRROR,
            interface="eth5",
            bridge_name="br0",
        )

        write_env_file(config, path=env_file)

        contents = open(env_file).read()
        assert "PCAP_IFACE=eth5" in contents

    def test_bridge_mode_env_file(self, tmp_path):
        """In bridge mode, PCAP_IFACE should be the bridge name."""
        env_file = str(tmp_path / "capture.env")

        config = CaptureConfig(
            mode=CaptureMode.BRIDGE,
            interface="enp2s0",
            bridge_name="br0",
        )

        write_env_file(config, path=env_file)

        contents = open(env_file).read()
        assert "PCAP_IFACE=br0" in contents


class TestInvalidMode:
    """Tests for invalid mode handling."""

    def test_invalid_mode_defaults_to_bridge_from_file(self, tmp_path):
        """Invalid mode in INI file should default to bridge."""
        config_file = tmp_path / "capture-mode.conf"
        config_file.write_text(
            "[capture]\n"
            "mode = span\n"
            "interface = enp2s0\n"
            "\n"
            "[bridge]\n"
            "wan_interface = eth0\n"
            "lan_interface = eth1\n"
        )

        config = load_capture_config(path=str(config_file))

        assert config.mode == CaptureMode.BRIDGE

    def test_invalid_mode_defaults_to_bridge_from_env(self, tmp_path):
        """Invalid CAPTURE_MODE env var should default to bridge."""
        fake_path = str(tmp_path / "nonexistent.conf")

        with patch.dict(os.environ, {"CAPTURE_MODE": "passive"}, clear=False):
            config = load_capture_config(path=fake_path)

        assert config.mode == CaptureMode.BRIDGE


class TestDhcpGatewaySection:
    """Tests for the [dhcp_gateway] section."""

    def test_defaults(self):
        config = CaptureConfig()
        assert config.dhcp_subnet == "10.77.0.0/24"
        assert config.dhcp_upstream_address == ""
        assert config.dhcp_upstream_gateway == ""
        assert config.dhcp_enabled is False

    def test_missing_section_loads_defaults(self, tmp_path):
        """Files written before DHCP gateway mode existed still load."""
        config_file = tmp_path / "capture-mode.conf"
        config_file.write_text(
            "[capture]\nmode = mirror\ninterface = enp2s0\n\n"
            "[bridge]\nwan_interface = eth0\nlan_interface = eth1\n"
        )

        config = load_capture_config(path=str(config_file))

        assert config.mode == CaptureMode.MIRROR
        assert config.dhcp_subnet == "10.77.0.0/24"
        assert config.dhcp_upstream_gateway == ""
        assert config.dhcp_enabled is False

    def test_load_dhcp_section(self, tmp_path):
        config_file = tmp_path / "capture-mode.conf"
        config_file.write_text(
            "[capture]\nmode = dhcp_gateway\ninterface = enp1s0\nmanagement =\n\n"
            "[dhcp_gateway]\n"
            "subnet = 10.88.0.0/24\n"
            "upstream_address = 192.168.1.50/24\n"
            "upstream_gateway = 192.168.1.1\n"
            "dhcp_enabled = true\n"
        )

        config = load_capture_config(path=str(config_file))

        assert config.mode == CaptureMode.DHCP_GATEWAY
        assert config.interface == "enp1s0"
        assert config.dhcp_subnet == "10.88.0.0/24"
        assert config.dhcp_upstream_address == "192.168.1.50/24"
        assert config.dhcp_upstream_gateway == "192.168.1.1"
        assert config.dhcp_enabled is True

    def test_inline_comments_from_design_doc_example(self, tmp_path):
        config_file = tmp_path / "capture-mode.conf"
        config_file.write_text(
            "[capture]\nmode = dhcp_gateway\ninterface = enp1s0\n\n"
            "[dhcp_gateway]\n"
            "subnet = 10.77.0.0/24\n"
            "upstream_address = 192.168.1.50/24     ; set by enable\n"
            "upstream_gateway = 192.168.1.1         ; set by enable\n"
            "dhcp_enabled = false                   ; DHCP server on/off\n"
        )

        config = load_capture_config(path=str(config_file))

        assert config.dhcp_upstream_address == "192.168.1.50/24"
        assert config.dhcp_upstream_gateway == "192.168.1.1"
        assert config.dhcp_enabled is False

    def test_invalid_dhcp_enabled_reads_as_off(self, tmp_path):
        config_file = tmp_path / "capture-mode.conf"
        config_file.write_text(
            "[capture]\nmode = dhcp_gateway\n\n[dhcp_gateway]\ndhcp_enabled = maybe\n"
        )

        config = load_capture_config(path=str(config_file))

        assert config.dhcp_enabled is False

    def test_dhcp_roundtrip(self, tmp_path):
        config_file = str(tmp_path / "capture-mode.conf")
        original = CaptureConfig(
            mode=CaptureMode.DHCP_GATEWAY,
            interface="enp1s0",
            dhcp_subnet="172.20.0.0/16",
            dhcp_upstream_address="192.168.1.50/24",
            dhcp_upstream_gateway="192.168.1.1",
            dhcp_enabled=True,
        )

        save_capture_config(original, path=config_file)
        loaded = load_capture_config(path=config_file)

        assert loaded == original
        assert "[dhcp_gateway]" in open(config_file).read()
        assert "dhcp_enabled = true" in open(config_file).read()

    def test_env_fallback_unchanged_for_dhcp_fields(self, tmp_path):
        fake_path = str(tmp_path / "nonexistent.conf")
        with patch.dict(
            os.environ, {"CAPTURE_MODE": "dhcp_gateway", "PCAP_IFACE": "enp1s0"}
        ):
            config = load_capture_config(path=fake_path)

        assert config.mode == CaptureMode.DHCP_GATEWAY
        assert config.interface == "enp1s0"
        assert config.dhcp_subnet == "10.77.0.0/24"
        assert config.dhcp_enabled is False


class TestEnvFileFilter:
    """Tests for PCAP_FILTER and PCAP_IFACE per mode."""

    def test_dhcp_gateway_env_file(self, tmp_path):
        env_file = tmp_path / "capture.env"
        config = CaptureConfig(
            mode=CaptureMode.DHCP_GATEWAY,
            interface="enp1s0",
            bridge_name="br0",
            dhcp_subnet="10.77.0.0/24",
        )

        write_env_file(config, path=str(env_file))

        assert env_file.read_text() == (
            "CAPTURE_MODE=dhcp_gateway\n"
            "PCAP_IFACE=enp1s0\n"
            "PCAP_FILTER=net 10.77.0.0/24 or udp port 67 or udp port 68\n"
        )

    @pytest.mark.parametrize(
        "mode, iface", [(CaptureMode.MIRROR, "eth5"), (CaptureMode.BRIDGE, "br0")]
    )
    def test_other_modes_have_empty_filter(self, tmp_path, mode, iface):
        env_file = tmp_path / "capture.env"
        config = CaptureConfig(mode=mode, interface="eth5", bridge_name="br0")

        write_env_file(config, path=str(env_file))

        lines = env_file.read_text().splitlines()
        assert f"PCAP_IFACE={iface}" in lines
        assert "PCAP_FILTER=" in lines

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"interface": "enp1s0\nPCAP_FILTER=host 1.2.3.4"},
            {"interface": "x" * 16},
            {"interface": "enp1s0", "dhcp_subnet": "8.8.8.0/24"},
            {"interface": "enp1s0", "dhcp_subnet": "10.77.0.0/24 or host 1.2.3.4"},
        ],
    )
    def test_invalid_values_are_never_written(self, tmp_path, kwargs):
        env_file = tmp_path / "capture.env"
        env_file.write_text("CAPTURE_MODE=bridge\nPCAP_IFACE=br0\n")
        config = CaptureConfig(mode=CaptureMode.DHCP_GATEWAY, **kwargs)

        with pytest.raises(ValueError):
            write_env_file(config, path=str(env_file))

        assert env_file.read_text() == "CAPTURE_MODE=bridge\nPCAP_IFACE=br0\n"


class TestAtomicWrites:
    """Both files are written via a temp file in the same dir + os.replace."""

    def test_save_uses_replace_and_leaves_no_temp_files(self, tmp_path):
        config_file = tmp_path / "capture-mode.conf"
        with patch.object(capture_config.os, "replace", wraps=os.replace) as spy:
            save_capture_config(CaptureConfig(), path=str(config_file))
        src, dst = spy.call_args.args
        assert os.path.dirname(src) == str(tmp_path)
        assert dst == str(config_file)
        assert os.listdir(tmp_path) == ["capture-mode.conf"]

    def test_env_file_uses_replace(self, tmp_path):
        env_file = tmp_path / "capture.env"
        with patch.object(capture_config.os, "replace", wraps=os.replace) as spy:
            write_env_file(CaptureConfig(), path=str(env_file))
        assert spy.call_args.args[1] == str(env_file)
        assert os.listdir(tmp_path) == ["capture.env"]

    def test_failed_write_keeps_old_file(self, tmp_path):
        config_file = tmp_path / "capture-mode.conf"
        config_file.write_text("old contents\n")
        with patch.object(
            capture_config.os, "replace", side_effect=OSError("disk full")
        ):
            with pytest.raises(OSError):
                save_capture_config(CaptureConfig(), path=str(config_file))
        assert config_file.read_text() == "old contents\n"
        assert os.listdir(tmp_path) == ["capture-mode.conf"]

    def test_files_are_world_readable(self, tmp_path):
        """Capture containers read capture.env, so keep the old 0644 mode."""
        config_file = tmp_path / "capture-mode.conf"
        env_file = tmp_path / "capture.env"
        save_capture_config(CaptureConfig(), path=str(config_file))
        write_env_file(CaptureConfig(), path=str(env_file))
        assert stat.S_IMODE(config_file.stat().st_mode) == 0o644
        assert stat.S_IMODE(env_file.stat().st_mode) == 0o644

    def test_write_file_atomic_mode(self, tmp_path):
        target = tmp_path / "script.sh"
        write_file_atomic(str(target), "#!/bin/sh\n", 0o755)
        assert target.read_text() == "#!/bin/sh\n"
        assert stat.S_IMODE(target.stat().st_mode) == 0o755


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
