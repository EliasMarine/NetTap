"""NET-191 slice 3: the owner rules validator refuses everything outside the detection-only subset."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services.owner_rules_validator import (
    FORBIDDEN,
    MAX_BYTES,
    MAX_RULES,
    split_options,
    validate,
)

OPTS = 'msg:"test"; content:"x"; sid:1000001; rev:1;'


def rule(options: str = OPTS, action: str = "alert") -> str:
    return f"{action} tcp any any -> any any ({options})"


def only_error(content: str) -> dict:
    errors, _ = validate(content)
    assert len(errors) == 1, errors
    return errors[0]


class TestAccepted:
    def test_a_plain_alert_rule(self):
        assert validate(rule()) == ([], 1)

    def test_empty_content_clears_the_rules(self):
        assert validate("") == ([], 0)
        assert validate("\n  \n# just a comment\n") == ([], 0)

    @pytest.mark.parametrize(
        "options",
        [
            'msg:"a; b"; content:"x"; sid:1000001;',
            'msg:"x"; content:"a;b|3b|"; sid:1000001;',
            r'msg:"a \"quoted\"; part"; content:"x"; sid:1000001;',
            r'msg:"escaped \; semicolon"; sid:1000001;',
        ],
    )
    def test_a_semicolon_inside_quotes_is_text(self, options):
        assert validate(rule(options)) == ([], 1)

    @pytest.mark.parametrize("word", sorted(FORBIDDEN))
    def test_a_forbidden_word_inside_quotes_is_text(self, word):
        assert validate(rule(f'msg:"{word}: no"; content:"{word};"; sid:1000001;')) == (
            [],
            1,
        )

    def test_the_sid_range_ends_are_allowed(self):
        rules = rule("sid:1000000;") + "\n" + rule("sid:1999999;")
        assert validate(rules) == ([], 2)

    def test_comments_and_blank_lines_are_not_rules(self):
        assert validate(f"# {rule('sid:5;')}\n\n{rule()}\n") == ([], 1)


class TestRefused:
    @pytest.mark.parametrize(
        "action", ["pass", "drop", "reject", "rejectsrc", "config"]
    )
    def test_actions_other_than_alert(self, action):
        error = only_error(rule(action=action))
        assert error == {"line": 1, "message": "Only alert rules can be used."}

    @pytest.mark.parametrize("word", ["lua", "luajit", "luaxform"])
    def test_each_lua_keyword(self, word):
        error = only_error(rule(f'msg:"x"; {word}:script.lua; sid:1000001;'))
        assert error["message"] == f'"{word}" can\'t be used in your own rules.'

    @pytest.mark.parametrize(
        "option",
        [
            "config:logging disable,tx,rule",  # config inside an alert
            "bypass",
            "dataset:isset,bad,type string,load bad.lst",
            "datarep:bad,>,1",
            "filestore",
            "  LUA : script.lua",  # case and spaces don't hide a keyword
        ],
    )
    def test_keywords_that_change_the_engine_or_touch_files(self, option):
        error = only_error(rule(f'msg:"x"; {option}; sid:1000001;'))
        assert "can't be used in your own rules" in error["message"]

    def test_a_keyword_after_a_quoted_semicolon_is_still_seen(self):
        error = only_error(rule('msg:"a;b"; lua:x.lua; sid:1000001;'))
        assert error["message"] == '"lua" can\'t be used in your own rules.'

    @pytest.mark.parametrize(
        "options", ['msg:"x"; rev:1;', "sid:1000001; sid:1000002;"]
    )
    def test_missing_or_two_sids(self, options):
        assert (
            only_error(rule(options))["message"] == "Each rule needs exactly one sid."
        )

    @pytest.mark.parametrize(
        "sid", ["999999", "2000000", "2010935", "-1000001", "1e6", "abc"]
    )
    def test_out_of_range_sid(self, sid):
        error = only_error(rule(f"sid:{sid};"))
        assert error["message"] == "The sid must be a number from 1000000 to 1999999."

    def test_duplicate_sid_names_the_first_line(self):
        content = f"{rule()}\n# note\n{rule()}"
        assert only_error(content) == {
            "line": 3,
            "message": "sid 1000001 is already used on line 1.",
        }

    @pytest.mark.parametrize(
        "line, message",
        [
            (
                'alert tcp any any -> any any (msg:"x; sid:1000001;)',
                "A quote is never closed.",
            ),
            (
                "alert tcp any any -> any any (sid:1000001; rev:1)",
                'The last option must end with ";".',
            ),
            (
                "alert tcp any any -> any any (sid:1000001;",
                'A rule needs its options in "( … )" on one line.',
            ),
            (
                "alert tcp any any -> any any",
                'A rule needs its options in "( … )" on one line.',
            ),
            ('alert tcp any any -> any any (msg:"x\\)', "A quote is never closed."),
        ],
    )
    def test_broken_rule_text(self, line, message):
        assert only_error(line)["message"] == message

    def test_errors_carry_their_line_numbers(self):
        content = "\n".join([rule(), rule(action="drop"), "", rule("sid:7;")])
        errors, count = validate(content)
        assert [e["line"] for e in errors] == [2, 4]
        assert count == 3


class TestLimits:
    def test_just_under_the_size_cap(self):
        line = rule()
        content = line + "\n" + "#" * (MAX_BYTES - len(line) - 1)
        assert len(content.encode()) == MAX_BYTES
        assert validate(content) == ([], 1)

    def test_just_over_the_size_cap(self):
        content = rule() + "\n" + "#" * (MAX_BYTES - len(rule()))
        assert len(content.encode()) == MAX_BYTES + 1
        assert validate(content) == (
            [{"line": None, "message": "Your rules are over 256 KB."}],
            0,
        )

    def test_the_size_cap_counts_utf8_bytes(self):
        content = "# " + "é" * (MAX_BYTES // 2)
        assert validate(content)[0][0]["message"] == "Your rules are over 256 KB."

    def test_the_most_rules(self):
        content = "\n".join(rule(f"sid:{1000000 + i};") for i in range(MAX_RULES))
        assert validate(content) == ([], MAX_RULES)

    def test_one_rule_too_many(self):
        content = "\n".join(rule(f"sid:{1000000 + i};") for i in range(MAX_RULES + 1))
        errors, count = validate(content)
        assert count == MAX_RULES + 1
        assert errors == [
            {"line": None, "message": "That is 2001 rules; the most is 2000."}
        ]


def test_split_options_keeps_quotes_and_escapes():
    assert split_options(r'msg:"a;b"; content:"\"x\""; sid:1;') == [
        'msg:"a;b"',
        r'content:"\"x\""',
        "sid:1",
    ]
