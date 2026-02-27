"""
NetTap ILM Policy Applicator

Reads the three-tier ISM policy definitions from the ILM policy JSON file
and applies them to OpenSearch via the ISM plugin API. Handles create,
update, and skip-if-identical logic for each policy.

Usage:
    from storage.ilm import apply_ilm_policies
    results = apply_ilm_policies("http://localhost:9200")
"""

import os
import json
import logging
import hashlib
from typing import Any

from opensearchpy import OpenSearch, exceptions as os_exceptions

logger = logging.getLogger("nettap.storage.ilm")

# Default path inside the container; override with ILM_POLICY_PATH env var
DEFAULT_ILM_POLICY_PATH = "/opt/nettap/config/opensearch/ilm-policy.json"


def _load_policies(policy_path: str | None = None) -> dict[str, dict]:
    """Load ILM policies from the JSON configuration file.

    Args:
        policy_path: Path to the ILM policy JSON file. If None, uses
                     the ILM_POLICY_PATH env var or the default container path.

    Returns:
        Dict mapping policy_name -> policy_body (the inner "policy" object
        suitable for PUT to _plugins/_ism/policies/<name>).

    Raises:
        FileNotFoundError: If the policy file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
        KeyError: If the file structure is missing the "policies" key.
    """
    path = policy_path or os.environ.get("ILM_POLICY_PATH", DEFAULT_ILM_POLICY_PATH)
    logger.info("Loading ILM policies from %s", path)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "policies" not in data:
        raise KeyError(
            f"ILM policy file at {path} is missing the top-level 'policies' key"
        )

    policies: dict[str, dict] = {}
    for name, body in data["policies"].items():
        # Each entry should have a "policy" key containing the ISM policy body
        if "policy" not in body:
            logger.warning(
                "Policy '%s' is missing the inner 'policy' key, skipping", name
            )
            continue
        policies[name] = body  # Keep the outer wrapper with "policy" inside
    return policies


def _policy_hash(policy_body: dict) -> str:
    """Compute a deterministic hash of a policy body for comparison.

    We serialize with sorted keys and compare the SHA-256 digest to detect
    whether the local policy definition differs from what is already in
    OpenSearch.
    """
    canonical = json.dumps(policy_body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_remote_policy(remote_response: dict) -> dict:
    """Extract the comparable policy body from an OpenSearch GET response.

    The GET _plugins/_ism/policies/<name> response wraps the policy with
    metadata fields (_id, _version, _seq_no, _primary_term). We strip
    those to get the policy body that is comparable to our local definition.
    """
    # The response has the policy at the top level with extra metadata
    policy_body = {}
    if "policy" in remote_response:
        # Clone the policy and strip ISM metadata fields that OpenSearch adds
        raw = dict(remote_response["policy"])
        # OpenSearch adds these fields; remove them for comparison
        for meta_key in (
            "policy_id",
            "last_updated_time",
            "schema_version",
            "error_notification",
        ):
            raw.pop(meta_key, None)
        policy_body = {"policy": raw}
    return policy_body


def _get_existing_policy(
    client: OpenSearch, policy_name: str
) -> tuple[dict | None, int | None, int | None]:
    """Fetch an existing ISM policy from OpenSearch.

    Returns:
        Tuple of (policy_response_dict, seq_no, primary_term).
        All None if the policy does not exist.
    """
    try:
        response = client.transport.perform_request(
            "GET", f"/_plugins/_ism/policies/{policy_name}"
        )
        seq_no = response.get("_seq_no")
        primary_term = response.get("_primary_term")
        return response, seq_no, primary_term
    except os_exceptions.NotFoundError:
        return None, None, None
    except Exception as exc:
        logger.error("Error fetching existing policy '%s': %s", policy_name, exc)
        raise


def _create_policy(client: OpenSearch, policy_name: str, policy_body: dict) -> str:
    """Create a new ISM policy in OpenSearch.

    Returns:
        "created" on success.

    Raises:
        Exception from opensearch-py on failure.
    """
    client.transport.perform_request(
        "PUT",
        f"/_plugins/_ism/policies/{policy_name}",
        body=policy_body,
    )
    logger.info("Created ISM policy '%s'", policy_name)
    return "created"


def _update_policy(
    client: OpenSearch,
    policy_name: str,
    policy_body: dict,
    seq_no: int,
    primary_term: int,
) -> str:
    """Update an existing ISM policy using optimistic concurrency control.

    Returns:
        "updated" on success.

    Raises:
        Exception from opensearch-py on failure (including version conflicts).
    """
    client.transport.perform_request(
        "PUT",
        f"/_plugins/_ism/policies/{policy_name}",
        params={"if_seq_no": seq_no, "if_primary_term": primary_term},
        body=policy_body,
    )
    logger.info("Updated ISM policy '%s'", policy_name)
    return "updated"


def apply_ilm_policies(
    opensearch_url: str,
    policy_path: str | None = None,
    *,
    verify_certs: bool = False,
    http_auth: tuple[str, str] | None = None,
) -> dict[str, str]:
    """Apply all NetTap ILM/ISM policies to OpenSearch.

    Reads the policy definitions from the JSON config file, then for each
    policy:
      - If it does not exist in OpenSearch, creates it.
      - If it exists but differs from the local definition, updates it.
      - If it exists and is identical, skips it.

    Args:
        opensearch_url: Base URL of the OpenSearch cluster
            (e.g., "http://localhost:9200").
        policy_path: Optional override path to the ILM policy JSON file.
            If None, uses ILM_POLICY_PATH env var or default container path.
        verify_certs: Whether to verify TLS certificates (default False
            for internal Docker network communication).
        http_auth: Optional (username, password) tuple for authentication.

    Returns:
        Dict mapping policy_name -> status string.
        Possible status values:
            "created"  — Policy did not exist and was created.
            "updated"  — Policy existed but differed; updated in place.
            "unchanged" — Policy exists and matches local definition.
            "error: <message>" — An error occurred for this policy.

    Example:
        >>> results = apply_ilm_policies("http://opensearch:9200")
        >>> print(results)
        {
            "nettap-hot-policy": "created",
            "nettap-warm-policy": "unchanged",
            "nettap-cold-policy": "updated"
        }
    """
    # Load local policy definitions
    policies = _load_policies(policy_path)
    if not policies:
        logger.warning("No policies found in configuration file")
        return {}

    # Build OpenSearch client
    # Parse host/port from URL
    client_kwargs: dict[str, Any] = {
        "verify_certs": verify_certs,
        "ssl_show_warn": False,
    }
    if http_auth:
        client_kwargs["http_auth"] = http_auth

    # opensearch-py accepts a list of host strings or dicts
    client = OpenSearch(
        hosts=[opensearch_url],
        **client_kwargs,
    )

    results: dict[str, str] = {}

    for policy_name, policy_body in policies.items():
        try:
            logger.info("Processing ISM policy '%s'...", policy_name)

            # Check if the policy already exists
            existing, seq_no, primary_term = _get_existing_policy(client, policy_name)

            if existing is None:
                # Policy does not exist — create it
                results[policy_name] = _create_policy(client, policy_name, policy_body)
            else:
                # Policy exists — compare with local definition
                normalized_remote = _normalize_remote_policy(existing)
                local_hash = _policy_hash(policy_body)
                remote_hash = _policy_hash(normalized_remote)

                if local_hash == remote_hash:
                    logger.info("ISM policy '%s' is unchanged, skipping", policy_name)
                    results[policy_name] = "unchanged"
                else:
                    logger.info(
                        "ISM policy '%s' has changed, updating (local=%s, remote=%s)",
                        policy_name,
                        local_hash[:12],
                        remote_hash[:12],
                    )
                    results[policy_name] = _update_policy(
                        client,
                        policy_name,
                        policy_body,
                        seq_no,
                        primary_term,
                    )
        except Exception as exc:
            error_msg = f"error: {exc}"
            logger.error("Failed to apply ISM policy '%s': %s", policy_name, exc)
            results[policy_name] = error_msg

    # Summary log
    created = sum(1 for v in results.values() if v == "created")
    updated = sum(1 for v in results.values() if v == "updated")
    unchanged = sum(1 for v in results.values() if v == "unchanged")
    errors = sum(1 for v in results.values() if v.startswith("error"))
    logger.info(
        "ILM policy application complete: %d created, %d updated, "
        "%d unchanged, %d errors",
        created,
        updated,
        unchanged,
        errors,
    )

    return results
