"""
Tests for daemon/services/cyberchef_service.py

All tests use mocks -- no Docker or CyberChef container required.
"""

import asyncio
import base64
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import aiohttp

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.cyberchef_service import (
    CyberChefService,
    BUILTIN_RECIPES,
    CYBERCHEF_CONTAINER,
    CYBERCHEF_INTERNAL_URL,
)


class TestGetRecipesAll(unittest.TestCase):
    """test_get_recipes_all: Verify all recipes are returned."""

    def test_get_recipes_all(self):
        """All built-in recipes should be returned when no category filter is given."""
        svc = CyberChefService()
        recipes = svc.get_recipes()
        self.assertEqual(len(recipes), len(BUILTIN_RECIPES))
        # Each recipe dict should have the expected keys
        for recipe in recipes:
            self.assertIn("name", recipe)
            self.assertIn("description", recipe)
            self.assertIn("category", recipe)
            self.assertIn("url", recipe)
            # the web page posts the fragment back to build a link
            self.assertTrue(recipe["recipe_fragment"].startswith("#recipe="))
            # browser link through the nginx proxy, not the internal container URL
            self.assertTrue(recipe["url"].startswith("/cyberchef/#recipe="))


class TestGetRecipesByCategory(unittest.TestCase):
    """test_get_recipes_by_category: Filter by known categories."""

    def test_get_recipes_decode(self):
        """Filter by 'decode' should return only decode recipes."""
        svc = CyberChefService()
        recipes = svc.get_recipes(category="decode")
        self.assertTrue(len(recipes) > 0)
        for recipe in recipes:
            self.assertEqual(recipe["category"], "decode")

    def test_get_recipes_network(self):
        """Filter by 'network' should return only network recipes."""
        svc = CyberChefService()
        recipes = svc.get_recipes(category="network")
        self.assertTrue(len(recipes) > 0)
        for recipe in recipes:
            self.assertEqual(recipe["category"], "network")

    def test_get_recipes_forensic(self):
        """Filter by 'forensic' should return only forensic recipes."""
        svc = CyberChefService()
        recipes = svc.get_recipes(category="forensic")
        self.assertTrue(len(recipes) > 0)
        for recipe in recipes:
            self.assertEqual(recipe["category"], "forensic")

    def test_get_recipes_crypto(self):
        """Filter by 'crypto' should return only crypto recipes."""
        svc = CyberChefService()
        recipes = svc.get_recipes(category="crypto")
        self.assertTrue(len(recipes) > 0)
        for recipe in recipes:
            self.assertEqual(recipe["category"], "crypto")


class TestGetRecipesEmptyCategory(unittest.TestCase):
    """test_get_recipes_empty_category: Unknown category returns empty."""

    def test_get_recipes_unknown_category(self):
        """An unknown category should return an empty list."""
        svc = CyberChefService()
        recipes = svc.get_recipes(category="nonexistent_category")
        self.assertEqual(recipes, [])

    def test_get_recipes_empty_string_returns_all(self):
        """Empty string category should return all recipes (no filter)."""
        svc = CyberChefService()
        recipes = svc.get_recipes(category="")
        self.assertEqual(len(recipes), len(BUILTIN_RECIPES))


class TestBuildRecipeUrlNoInput(unittest.TestCase):
    """test_build_recipe_url_no_input: Verify URL construction without input."""

    def test_build_url_no_input(self):
        """URL should be /cyberchef/ + recipe_fragment with no input appended."""
        svc = CyberChefService()
        fragment = "#recipe=From_Base64('A-Za-z0-9%2B/%3D',true,false)"
        url = svc.build_recipe_url(fragment)
        expected = f"/cyberchef/{fragment}"
        self.assertEqual(url, expected)

    def test_build_url_empty_input(self):
        """Empty input_data string should not append &input= parameter."""
        svc = CyberChefService()
        fragment = "#recipe=URL_Decode()"
        url = svc.build_recipe_url(fragment, input_data="")
        self.assertNotIn("&input=", url)


class TestBuildRecipeUrlWithInput(unittest.TestCase):
    """test_build_recipe_url_with_input: Verify base64-encoded input appended."""

    def test_build_url_with_input(self):
        """Input data should be unpadded base64, percent-encoded, as &input=."""
        svc = CyberChefService()
        fragment = "#recipe=From_Base64('A-Za-z0-9%2B/%3D',true,false)"
        input_data = "aGVsbG8gbmV0dGFw"
        url = svc.build_recipe_url(fragment, input_data=input_data)
        # b64("aGVsbG8gbmV0dGFw") = "YUdWc2JHOGdibVYwZEdGdw==" -> padding dropped
        self.assertTrue(url.endswith("&input=YUdWc2JHOGdibVYwZEdGdw"))

    def test_build_url_input_round_trips_through_cyberchef_parsing(self):
        """'+', '/' and padding survive CyberChef's hash parsing ("=" split, "+" -> space)."""
        svc = CyberChefService()
        input_data = "???>>>\xff"
        raw = base64.b64encode(input_data.encode()).decode()
        self.assertTrue(all(c in raw for c in "+/="))  # the cases that used to break
        url = svc.build_recipe_url("#recipe=To_Hex('Space',0)", input_data=input_data)
        value = url.split("&input=", 1)[1]
        self.assertNotIn("=", value)
        self.assertNotIn("+", value)
        decoded = unquote(value.replace("+", " "))
        restored = base64.b64decode(decoded + "=" * (-len(decoded) % 4)).decode()
        self.assertEqual(restored, input_data)

    def test_build_url_with_input_replaces_existing_placeholder(self):
        """When fragment already has &input=, the placeholder should be replaced."""
        svc = CyberChefService()
        # DNS Packet Decode recipe has &input= at the end
        fragment = "#recipe=From_Hex('Auto')&input="
        input_data = "deadbeef"
        url = svc.build_recipe_url(fragment, input_data=input_data)
        encoded_input = base64.b64encode(input_data.encode()).decode().rstrip("=")
        self.assertIn(f"&input={encoded_input}", url)
        # Should NOT have a bare &input= left over
        self.assertNotIn("&input=&", url)

    def test_build_url_with_custom_public_path(self):
        """Links use the public path; the internal base_url is for health checks only."""
        svc = CyberChefService(base_url="http://localhost:9999", public_path="/chef")
        fragment = "#recipe=URL_Decode()"
        url = svc.build_recipe_url(fragment, input_data="test data")
        self.assertTrue(url.startswith("/chef/#recipe="))


_HEALTH_URL = f"{CYBERCHEF_INTERNAL_URL}/health"


def _patched_session(status=None, exc=None):
    """Patch aiohttp.ClientSession so GET /health returns `status` or raises `exc`.

    Plain unittest.mock on purpose: aioresponses lags aiohttp releases
    (0.7.9 breaks on aiohttp 3.14), and CI installs the newest aiohttp.
    """
    session = MagicMock()
    if exc is not None:
        session.get.side_effect = exc
    else:
        session.get.return_value.__aenter__.return_value.status = status
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    return patch("aiohttp.ClientSession", factory), session


class TestIsAvailableRunning(unittest.TestCase):
    """is_available() checks CyberChef's HTTP health endpoint."""

    def test_is_available_running(self):
        """A 200 from /health reports available=True with the URL."""

        async def run():
            patcher, session = _patched_session(status=200)
            with patcher:
                result = await CyberChefService().is_available()
            session.get.assert_called_once_with(_HEALTH_URL)
            self.assertTrue(result["available"])
            self.assertTrue(result["container_running"])
            self.assertEqual(result["container_name"], CYBERCHEF_CONTAINER)
            self.assertEqual(result["url"], CYBERCHEF_INTERNAL_URL)
            self.assertNotIn("error", result)

        asyncio.run(run())


class TestIsAvailableNotRunning(unittest.TestCase):
    """Non-200 responses and connection errors report unavailable."""

    def test_is_available_not_running(self):
        """A non-200 from /health reports available=False with no URL."""

        async def run():
            patcher, _ = _patched_session(status=503)
            with patcher:
                result = await CyberChefService().is_available()
            self.assertFalse(result["available"])
            self.assertFalse(result["container_running"])
            self.assertEqual(result["container_name"], CYBERCHEF_CONTAINER)
            self.assertIsNone(result["url"])
            self.assertNotIn("error", result)

        asyncio.run(run())

    def test_is_available_error(self):
        """A connection error reports unavailable and carries the error text."""

        async def run():
            patcher, _ = _patched_session(
                exc=aiohttp.ClientConnectionError("connection refused")
            )
            with patcher:
                result = await CyberChefService().is_available()
            self.assertFalse(result["available"])
            self.assertFalse(result["container_running"])
            self.assertIsNone(result["url"])
            self.assertIn("connection refused", result["error"])

        asyncio.run(run())


class TestGetStatusStructure(unittest.TestCase):
    """test_get_status_structure: Verify all keys present in get_status()."""

    def test_get_status_structure(self):
        """get_status() should return dict with service, base_url, recipe_count, categories."""
        svc = CyberChefService()
        status = svc.get_status()
        self.assertIn("service", status)
        self.assertIn("base_url", status)
        self.assertIn("recipe_count", status)
        self.assertIn("categories", status)

    def test_get_status_values(self):
        """Verify the actual values in get_status()."""
        svc = CyberChefService()
        status = svc.get_status()
        self.assertEqual(status["service"], "cyberchef")
        self.assertEqual(status["base_url"], CYBERCHEF_INTERNAL_URL)
        self.assertEqual(status["recipe_count"], len(BUILTIN_RECIPES))
        # Should have all four categories
        expected_categories = {"decode", "crypto", "network", "forensic"}
        self.assertEqual(set(status["categories"]), expected_categories)

    def test_get_status_custom_base_url(self):
        """Custom base_url should be reflected in get_status()."""
        custom_url = "http://custom:1234"
        svc = CyberChefService(base_url=custom_url)
        status = svc.get_status()
        self.assertEqual(status["base_url"], custom_url)


if __name__ == "__main__":
    unittest.main()
