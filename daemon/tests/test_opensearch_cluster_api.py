"""Tests for daemon/api/opensearch_cluster.py"""

import unittest
from unittest.mock import MagicMock
from aiohttp.test_utils import AioHTTPTestCase
from aiohttp import web
from api.opensearch_cluster import register_opensearch_cluster_routes


class TestOpenSearchClusterAPI(AioHTTPTestCase):
    async def get_application(self):
        app = web.Application()
        self.mock_storage = MagicMock()
        self.mock_client = MagicMock()
        self.mock_storage._client = self.mock_client
        # Set up nested mock attributes
        self.mock_client.cluster = MagicMock()
        self.mock_client.cat = MagicMock()
        register_opensearch_cluster_routes(app, self.mock_storage)
        return app

    async def test_cluster_health(self):
        """GET /api/opensearch/cluster returns health + stats."""
        self.mock_client.cluster.health.return_value = {
            "status": "green",
            "number_of_nodes": 1,
            "number_of_data_nodes": 1,
            "active_primary_shards": 5,
            "active_shards": 5,
        }
        self.mock_client.cluster.stats.return_value = {
            "indices": {
                "count": 10,
                "docs": {"count": 50000},
                "store": {"size_in_bytes": 1073741824},
            }
        }
        resp = await self.client.request("GET", "/api/opensearch/cluster")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "green")
        self.assertEqual(data["total_indices"], 10)
        self.assertEqual(data["total_docs"], 50000)
        self.assertEqual(data["total_size_bytes"], 1073741824)

    async def test_indices_list(self):
        """GET /api/opensearch/indices returns index list."""
        self.mock_client.cat.indices.return_value = [
            {"index": "arkime_sessions3-260305", "health": "green", "docs.count": "1000", "store.size": "10mb"},
            {"index": "arkime_sessions3-260304", "health": "green", "docs.count": "800", "store.size": "8mb"},
        ]
        resp = await self.client.request("GET", "/api/opensearch/indices")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("indices", data)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["indices"][0]["index"], "arkime_sessions3-260305")

    async def test_indices_empty(self):
        """GET /api/opensearch/indices handles empty response."""
        self.mock_client.cat.indices.return_value = []
        resp = await self.client.request("GET", "/api/opensearch/indices")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["count"], 0)

    async def test_shards(self):
        """GET /api/opensearch/shards returns shard allocation."""
        self.mock_client.cat.shards.return_value = [
            {"index": "arkime_sessions3-260305", "shard": "0", "prirep": "p", "state": "STARTED", "docs": "1000", "store": "10mb", "node": "node1"},
        ]
        resp = await self.client.request("GET", "/api/opensearch/shards")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("shards", data)
        self.assertEqual(data["count"], 1)

    async def test_templates(self):
        """GET /api/opensearch/templates returns template list."""
        self.mock_client.cat.templates.return_value = [
            {"name": "malcolm_template", "index_patterns": "[arkime_sessions3-*]", "order": "0"},
        ]
        resp = await self.client.request("GET", "/api/opensearch/templates")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("templates", data)
        self.assertEqual(data["count"], 1)

    async def test_cluster_health_error(self):
        """OpenSearch exception returns 500."""
        from opensearchpy import OpenSearchException
        self.mock_client.cluster.health.side_effect = OpenSearchException("timeout")
        resp = await self.client.request("GET", "/api/opensearch/cluster")
        self.assertEqual(resp.status, 500)

    async def test_indices_error(self):
        """OpenSearch exception on indices returns 500."""
        from opensearchpy import OpenSearchException
        self.mock_client.cat.indices.side_effect = OpenSearchException("timeout")
        resp = await self.client.request("GET", "/api/opensearch/indices")
        self.assertEqual(resp.status, 500)


if __name__ == "__main__":
    unittest.main()
