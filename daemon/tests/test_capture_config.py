"""
Tests for daemon/services/capture_config.py

Tests cover config loading from INI files, environment variables, defaults,
save/load roundtrips, and .env file generation for docker-compose.
Uses tmp_path fixture for temp files — no real /etc/nettap access required.
"""

import os
import sys
import unittest

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch

from services.capture_config import (
    CaptureConfig,
    load_capture_config,
    save_capture_config,
    write_env_file,
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
