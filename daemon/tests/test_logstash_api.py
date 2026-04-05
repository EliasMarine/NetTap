"""Tests for daemon/api/logstash.py — Logstash pipeline monitoring."""

import unittest
from unittest.mock import patch
from aiohttp.test_utils import AioHTTPTestCase
from aiohttp import web
from api.logstash import register_logstash_routes


class TestLogstashAPI(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        register_logstash_routes(app)
        return app

    @patch("api.logstash._fetch_logstash_api")
    async def test_stats_available(self, mock_fetch):
        """GET /api/logstash/stats returns stats when Logstash is available."""
        mock_fetch.return_value = {
            "jvm": {"mem": {"heap_used_in_bytes": 500000000, "heap_max_in_bytes": 1000000000}},
            "process": {"cpu": {"percent": 25}},
            "pipelines": {"main": {"events": {"in": 1000, "out": 990, "filtered": 10}}},
            "events": {"in": 1000, "out": 990},
        }
        resp = await self.client.request("GET", "/api/logstash/stats")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["available"])
        self.assertIn("jvm", data)
        self.assertIn("process", data)
        self.assertIn("pipelines", data)

    @patch("api.logstash._fetch_logstash_api")
    async def test_stats_unavailable(self, mock_fetch):
        """GET /api/logstash/stats returns 502 when Logstash is down."""
        mock_fetch.return_value = None
        resp = await self.client.request("GET", "/api/logstash/stats")
        self.assertEqual(resp.status, 502)
        data = await resp.json()
        self.assertFalse(data["available"])
        self.assertIn("error", data)

    @patch("api.logstash._fetch_logstash_api")
    async def test_pipelines(self, mock_fetch):
        """GET /api/logstash/pipelines returns per-pipeline breakdown."""
        mock_fetch.return_value = {
            "pipelines": {
                "main": {
                    "events": {"in": 1000, "out": 990, "filtered": 10, "duration_in_millis": 5000},
                    "plugins": {"inputs": [{"id": "beats"}], "filters": [], "outputs": [{"id": "opensearch"}]},
                    "reloads": {"successes": 1, "failures": 0},
                }
            }
        }
        resp = await self.client.request("GET", "/api/logstash/pipelines")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("pipelines", data)
        self.assertEqual(data["count"], 1)
        pipeline = data["pipelines"][0]
        self.assertEqual(pipeline["id"], "main")
        self.assertEqual(pipeline["events"]["in"], 1000)
        self.assertEqual(pipeline["events"]["out"], 990)
        self.assertEqual(pipeline["events"]["duration_ms"], 5000)

    @patch("api.logstash._fetch_logstash_api")
    async def test_pipelines_unavailable(self, mock_fetch):
        """GET /api/logstash/pipelines returns 502 when Logstash is down."""
        mock_fetch.return_value = None
        resp = await self.client.request("GET", "/api/logstash/pipelines")
        self.assertEqual(resp.status, 502)

    @patch("api.logstash._fetch_logstash_api")
    async def test_pipelines_multiple(self, mock_fetch):
        """Multiple pipelines are returned correctly."""
        mock_fetch.return_value = {
            "pipelines": {
                "main": {
                    "events": {"in": 1000, "out": 990, "filtered": 10, "duration_in_millis": 5000},
                    "plugins": {},
                    "reloads": {},
                },
                "dead_letter_queue": {
                    "events": {"in": 5, "out": 5, "filtered": 0, "duration_in_millis": 100},
                    "plugins": {},
                    "reloads": {},
                },
            }
        }
        resp = await self.client.request("GET", "/api/logstash/pipelines")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["count"], 2)


if __name__ == "__main__":
    unittest.main()
