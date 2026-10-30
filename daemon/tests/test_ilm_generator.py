"""
Tests for daemon/storage/ilm_generator.py

Covers policy count, per-tier retention days injection, fixed warm
transition, policy structure (states, rollover, ism_template), and
retry config consistency.
"""

from storage.ilm_generator import generate_ilm_policies
from storage.manager import RetentionConfig


# =========================================================================
# Policy generation — basic structure
# =========================================================================


class TestGeneratesThreePolicies:
    def test_generates_three_policies(self):
        """generate_ilm_policies() returns exactly 3 policies with correct names."""
        config = RetentionConfig()
        policies = generate_ilm_policies(config)
        assert len(policies) == 3
        assert "nettap-hot-policy" in policies
        assert "nettap-warm-policy" in policies
        assert "nettap-cold-policy" in policies


# =========================================================================
# Per-tier retention days
# =========================================================================


class TestHotPolicy:
    def test_hot_policy_uses_config_days(self):
        """Custom hot_days appears in the hot policy's delete transition."""
        config = RetentionConfig(hot_days=45)
        policies = generate_ilm_policies(config)
        hot = policies["nettap-hot-policy"]["policy"]

        # Find the delete transition on the "hot" state
        hot_state = next(s for s in hot["states"] if s["name"] == "hot")
        transition = hot_state["transitions"][0]
        assert transition["conditions"]["min_index_age"] == "45d"
        assert transition["state_name"] == "delete"

    def test_hot_policy_structure(self):
        """Verify hot policy state names, rollover size, retry, ism_template."""
        config = RetentionConfig()
        hot = generate_ilm_policies(config)["nettap-hot-policy"]["policy"]

        state_names = [s["name"] for s in hot["states"]]
        assert state_names == ["hot", "delete"]
        assert hot["default_state"] == "hot"

        # Rollover config
        hot_state = hot["states"][0]
        rollover = hot_state["actions"][0]["rollover"]
        assert rollover["min_primary_shard_size"] == "10gb"
        assert rollover["min_index_age"] == "1d"

        # ISM template
        assert hot["ism_template"][0]["index_patterns"] == ["zeek-*"]
        assert hot["ism_template"][0]["priority"] == 100


class TestWarmPolicy:
    def test_warm_policy_uses_config_days(self):
        """Custom warm_days appears in the warm policy's delete transition."""
        config = RetentionConfig(warm_days=100)
        policies = generate_ilm_policies(config)
        warm = policies["nettap-warm-policy"]["policy"]

        # The warm state transitions to delete at warm_days
        warm_state = next(s for s in warm["states"] if s["name"] == "warm")
        transition = warm_state["transitions"][0]
        assert transition["conditions"]["min_index_age"] == "100d"
        assert transition["state_name"] == "delete"

    def test_warm_transition_stays_7d(self):
        """The hot->warm transition is always '7d' regardless of config."""
        config = RetentionConfig(warm_days=365)
        warm = generate_ilm_policies(config)["nettap-warm-policy"]["policy"]

        hot_state = next(s for s in warm["states"] if s["name"] == "hot")
        transition = hot_state["transitions"][0]
        assert transition["conditions"]["min_index_age"] == "7d"
        assert transition["state_name"] == "warm"

    def test_warm_policy_structure(self):
        """3 states (hot/warm/delete), force_merge + read_only in warm state."""
        config = RetentionConfig()
        warm = generate_ilm_policies(config)["nettap-warm-policy"]["policy"]

        state_names = [s["name"] for s in warm["states"]]
        assert state_names == ["hot", "warm", "delete"]

        # Warm state actions
        warm_state = next(s for s in warm["states"] if s["name"] == "warm")
        action_keys = [
            list(set(a.keys()) - {"retry"})[0] for a in warm_state["actions"]
        ]
        assert "force_merge" in action_keys
        assert "read_only" in action_keys

        # ISM template
        assert warm["ism_template"][0]["index_patterns"] == ["suricata-*"]


class TestColdPolicy:
    def test_cold_policy_uses_config_days(self):
        """Custom cold_days appears in the cold policy's delete transition."""
        config = RetentionConfig(cold_days=7)
        policies = generate_ilm_policies(config)
        cold = policies["nettap-cold-policy"]["policy"]

        hot_state = next(s for s in cold["states"] if s["name"] == "hot")
        transition = hot_state["transitions"][0]
        assert transition["conditions"]["min_index_age"] == "7d"
        assert transition["state_name"] == "delete"

    def test_cold_policy_structure(self):
        """Verify arkime-*/pcap-* patterns and 20gb rollover."""
        config = RetentionConfig()
        cold = generate_ilm_policies(config)["nettap-cold-policy"]["policy"]

        state_names = [s["name"] for s in cold["states"]]
        assert state_names == ["hot", "delete"]

        # 20gb rollover
        hot_state = cold["states"][0]
        rollover = hot_state["actions"][0]["rollover"]
        assert rollover["min_primary_shard_size"] == "20gb"

        # ISM template covers both arkime and pcap
        patterns = cold["ism_template"][0]["index_patterns"]
        assert "arkime-*" in patterns
        assert "pcap-*" in patterns


# =========================================================================
# Default config matches static expectations
# =========================================================================


class TestDefaultConfigValues:
    def test_default_config_matches_static_json(self):
        """Default RetentionConfig(90/180/30) produces the expected policy days."""
        config = RetentionConfig()  # defaults: 90/180/30
        policies = generate_ilm_policies(config)

        # Hot: delete after 90d
        hot = policies["nettap-hot-policy"]["policy"]
        hot_state = next(s for s in hot["states"] if s["name"] == "hot")
        assert hot_state["transitions"][0]["conditions"]["min_index_age"] == "90d"

        # Warm: delete after 180d
        warm = policies["nettap-warm-policy"]["policy"]
        warm_state = next(s for s in warm["states"] if s["name"] == "warm")
        assert warm_state["transitions"][0]["conditions"]["min_index_age"] == "180d"

        # Cold: delete after 30d
        cold = policies["nettap-cold-policy"]["policy"]
        cold_hot = next(s for s in cold["states"] if s["name"] == "hot")
        assert cold_hot["transitions"][0]["conditions"]["min_index_age"] == "30d"

    def test_custom_config_values(self):
        """With (60/120/14), all three policies use those custom values."""
        config = RetentionConfig(hot_days=60, warm_days=120, cold_days=14)
        policies = generate_ilm_policies(config)

        hot = policies["nettap-hot-policy"]["policy"]
        hot_state = next(s for s in hot["states"] if s["name"] == "hot")
        assert hot_state["transitions"][0]["conditions"]["min_index_age"] == "60d"

        warm = policies["nettap-warm-policy"]["policy"]
        warm_state = next(s for s in warm["states"] if s["name"] == "warm")
        assert warm_state["transitions"][0]["conditions"]["min_index_age"] == "120d"

        cold = policies["nettap-cold-policy"]["policy"]
        cold_hot = next(s for s in cold["states"] if s["name"] == "hot")
        assert cold_hot["transitions"][0]["conditions"]["min_index_age"] == "14d"


# =========================================================================
# Retry config consistency
# =========================================================================


class TestRetryConfigConsistency:
    def test_retry_config_consistency(self):
        """All retry blocks across all policies use count=3, exponential, 10m."""
        config = RetentionConfig()
        policies = generate_ilm_policies(config)

        for policy_name, policy_wrapper in policies.items():
            for state in policy_wrapper["policy"]["states"]:
                for action in state["actions"]:
                    if "retry" in action:
                        retry = action["retry"]
                        assert retry["count"] == 3, (
                            f"{policy_name}/{state['name']}: count != 3"
                        )
                        assert retry["backoff"] == "exponential", (
                            f"{policy_name}/{state['name']}: backoff != exponential"
                        )
                        assert retry["delay"] == "10m", (
                            f"{policy_name}/{state['name']}: delay != 10m"
                        )
