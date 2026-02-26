"""
Tests for daemon/services/cyberchef_service.py

All tests use mocks -- no Docker or CyberChef container required.
"""

import asyncio
import base64
import unittest
from unittest.mock import AsyncMock, patch

import sys
import os

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.cyberchef_service import (
    CyberChefService,
    CyberChefRecipe,
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
            # URL should start with the base URL
            self.assertTrue(recipe["url"].startswith(CYBERCHEF_INTERNAL_URL))


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
        """URL should be base_url + / + recipe_fragment with no input appended."""
        svc = CyberChefService()
        fragment = "#recipe=From_Base64('A-Za-z0-9%2B/%3D',true,false)"
        url = svc.build_recipe_url(fragment)
        expected = f"{CYBERCHEF_INTERNAL_URL}/{fragment}"
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
        """Input data should be base64-encoded and appended as &input= parameter."""
        svc = CyberChefService()
        fragment = "#recipe=From_Base64('A-Za-z0-9%2B/%3D',true,false)"
        input_data = "SGVsbG8gV29ybGQ="
        url = svc.build_recipe_url(fragment, input_data=input_data)
        # Verify the input is base64-encoded in the URL
        encoded_input = base64.b64encode(input_data.encode()).decode()
        self.assertIn(f"&input={encoded_input}", url)

    def test_build_url_with_input_replaces_existing_placeholder(self):
        """When fragment already has &input=, the placeholder should be replaced."""
        svc = CyberChefService()
        # DNS Packet Decode recipe has &input= at the end
        fragment = "#recipe=From_Hex('Auto')&input="
        input_data = "deadbeef"
        url = svc.build_recipe_url(fragment, input_data=input_data)
        encoded_input = base64.b64encode(input_data.encode()).decode()
        self.assertIn(f"&input={encoded_input}", url)
        # Should NOT have a bare &input= left over
        self.assertNotIn("&input=&", url)

    def test_build_url_with_custom_base_url(self):
        """Custom base_url should be used in the constructed URL."""
        custom_url = "http://localhost:9999"
        svc = CyberChefService(base_url=custom_url)
        fragment = "#recipe=URL_Decode()"
        url = svc.build_recipe_url(fragment, input_data="test data")
        self.assertTrue(url.startswith(custom_url))


class TestIsAvailableRunning(unittest.TestCase):
    """test_is_available_running: Mock docker inspect returning 'true'."""

    def test_is_available_running(self):
        """When container is running, should report available=True with URL."""

        async def run():
            svc = CyberChefService()
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(
                return_value=(b"true\n", b"")
            )
            mock_process.returncode = 0

            with patch(
                "asyncio.create_subprocess_exec", new_callable=AsyncMock
            ) as mock_exec:
                mock_exec.return_value = mock_process
                result = await svc.is_available()
                self.assertTrue(result["available"])
                self.assertTrue(result["container_running"])
                self.assertEqual(result["container_name"], CYBERCHEF_CONTAINER)
                self.assertEqual(result["url"], CYBERCHEF_INTERNAL_URL)
                self.assertNotIn("error", result)

        asyncio.get_event_loop().run_until_complete(run())


class TestIsAvailableNotRunning(unittest.TestCase):
    """test_is_available_not_running: Mock docker inspect returning 'false'."""

    def test_is_available_not_running(self):
        """When container is not running, should report available=False with no URL."""

        async def run():
            svc = CyberChefService()
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(
                return_value=(b"false\n", b"")
            )
            mock_process.returncode = 0

            with patch(
                "asyncio.create_subprocess_exec", new_callable=AsyncMock
            ) as mock_exec:
                mock_exec.return_value = mock_process
                result = await svc.is_available()
                self.assertFalse(result["available"])
                self.assertFalse(result["container_running"])
                self.assertEqual(result["container_name"], CYBERCHEF_CONTAINER)
                self.assertIsNone(result["url"])

        asyncio.get_event_loop().run_until_complete(run())

    def test_is_available_error(self):
        """When docker inspect fails, should return error info."""

        async def run():
            svc = CyberChefService()

            with patch(
                "asyncio.create_subprocess_exec", new_callable=AsyncMock
            ) as mock_exec:
                mock_exec.side_effect = FileNotFoundError("docker not found")
                result = await svc.is_available()
                self.assertFalse(result["available"])
                self.assertFalse(result["container_running"])
                self.assertIsNone(result["url"])
                self.assertIn("error", result)
                self.assertIn("docker not found", result["error"])

        asyncio.get_event_loop().run_until_complete(run())


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
