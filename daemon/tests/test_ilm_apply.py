"""
Tests for ISM policy application in daemon/storage/ilm.py and
POST /api/ilm/apply in daemon/api/server.py (CR-017 / CR-038).

Covers attaching the policy to indices that already exist (ism_template
only catches new ones), idempotency when indices are already managed,
and that OpenSearch errors are reported per policy, never raised.
"""

from unittest.mock import MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase
from opensearchpy import exceptions as os_exceptions

from storage.ilm import apply_ilm_policies_from_config
from storage.ilm_generator import generate_ilm_policies
from storage.manager import RetentionConfig

TARGET = "arkime_sessions3-*,malcolm_beats_*,zeek-*"


def _fake_opensearch(post_responses=None, post_error=None):
    """A mock client: no policy exists yet, PUT succeeds, POSTs as given."""
    calls = []

    def perform_request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("body")))
        if method == "GET":
            raise os_exceptions.NotFoundError(404, "not found", {})
        if method == "POST":
            if post_error:
                raise post_error
            return (post_responses or {}).get(url, {"updated_indices": 0})
        return {}

    client = MagicMock()
    client.transport.perform_request.side_effect = perform_request
    return client, calls


def _apply(client):
    policies = generate_ilm_policies(RetentionConfig())
    with patch("storage.ilm.OpenSearch", return_value=client):
        return apply_ilm_policies_from_config("https://opensearch:9200", policies)


class TestAttachToExistingIndices:
    def test_add_and_change_policy_target_malcolm_indices(self):
        """Existing indices get the policy, and managed ones get the new version."""
        client, calls = _fake_opensearch()

        results = _apply(client)

        assert results == {"nettap-hot-policy": "created"}
        posts = [(url, body) for method, url, body in calls if method == "POST"]
        assert posts == [
            (f"/_plugins/_ism/add/{TARGET}", {"policy_id": "nettap-hot-policy"}),
            (
                f"/_plugins/_ism/change_policy/{TARGET}",
                {"policy_id": "nettap-hot-policy"},
            ),
        ]

    def test_already_managed_indices_are_not_errors(self):
        """Re-running is idempotent: 'already has a policy' is expected."""
        already = {
            "updated_indices": 0,
            "failures": True,
            "failed_indices": [
                {
                    "index_name": "arkime_sessions3-261029",
                    "reason": "This index already has a policy, use the update "
                    "policy API to update index policies",
                }
            ],
        }
        client, _ = _fake_opensearch({f"/_plugins/_ism/add/{TARGET}": already})

        assert _apply(client) == {"nettap-hot-policy": "created"}

    def test_attach_failure_is_reported_not_raised(self):
        """A failed attach marks the policy as an error so the retry runs."""
        client, _ = _fake_opensearch(
            post_error=os_exceptions.AuthorizationException(403, "forbidden", {})
        )

        results = _apply(client)

        assert results["nettap-hot-policy"].startswith("error")

    def test_opensearch_down_does_not_raise(self):
        """Daemon startup survives OpenSearch being unreachable."""
        client = MagicMock()
        client.transport.perform_request.side_effect = os_exceptions.ConnectionError(
            "N/A", "connection refused", None
        )

        results = _apply(client)

        assert results["nettap-hot-policy"].startswith("error")


class TestIlmApplyEndpoint(AioHTTPTestCase):
    """POST /api/ilm/apply applies the user's retention, not the static file."""

    async def get_application(self):
        from api.server import IlmSyncState, handle_ilm_apply

        app = web.Application()
        storage = MagicMock()
        storage.config = RetentionConfig(hot_days=14)
        app["storage"] = storage
        app["opensearch_url"] = "https://opensearch:9200"
        app["http_auth"] = ("admin", "secret")
        app["ilm_sync"] = IlmSyncState()
        app.router.add_post("/api/ilm/apply", handle_ilm_apply)
        return app

    async def test_applies_current_retention_with_auth(self):
        with patch(
            "api.server.apply_ilm_policies_from_config",
            return_value={"nettap-hot-policy": "updated"},
        ) as mock_apply:
            resp = await self.client.request("POST", "/api/ilm/apply")

        self.assertEqual(resp.status, 200)
        url, policies = mock_apply.call_args.args
        self.assertEqual(url, "https://opensearch:9200")
        self.assertEqual(policies, generate_ilm_policies(RetentionConfig(hot_days=14)))
        self.assertEqual(mock_apply.call_args.kwargs["http_auth"], ("admin", "secret"))
