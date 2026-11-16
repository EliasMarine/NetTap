"""scripts/check_release_version.py fails a tag that doesn't match the active NETTAP_VERSION."""

import importlib.util
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location(
    "check_release_version", os.path.join(REPO, "scripts", "check_release_version.py")
)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def _file(tmp_path, text):
    path = tmp_path / "version_manager.py"
    path.write_text(text)
    return str(path)


def test_the_real_file_matches_its_own_version():
    from services.version_manager import NETTAP_VERSION

    assert guard.check(f"v{NETTAP_VERSION}") is None


def test_a_matching_tag_passes(tmp_path):
    assert (
        guard.check(
            "v0.4.0-alpha.3", _file(tmp_path, 'NETTAP_VERSION = "0.4.0-alpha.3"\n')
        )
        is None
    )


def test_a_different_tag_fails(tmp_path):
    problem = guard.check(
        "v0.4.0-alpha.3", _file(tmp_path, 'NETTAP_VERSION = "0.4.0-alpha.2"\n')
    )
    assert "0.4.0-alpha.2" in problem and "0.4.0-alpha.3" in problem


def test_an_old_value_kept_in_a_comment_does_not_count(tmp_path):
    text = (
        '# OLD CODE: NETTAP_VERSION = "0.4.0-alpha.3" (kept per the preservation policy)\n'
        'NETTAP_VERSION = "0.4.0-alpha.2"\n'
    )
    assert guard.check("v0.4.0-alpha.3", _file(tmp_path, text)) is not None


def test_a_missing_or_computed_value_fails(tmp_path):
    assert guard.check("v1.0.0", _file(tmp_path, "OTHER = 1\n")) is not None
    assert (
        guard.check("v1.0.0", _file(tmp_path, 'NETTAP_VERSION = "1." + "0.0"\n'))
        is not None
    )
