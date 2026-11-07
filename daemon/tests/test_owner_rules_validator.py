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
HEADER = (
    'A rule is "alert", 6 more header fields, then its options in "( … )". '
    "Lists in [ ] can't contain spaces."
)
CONTROL = "This line has a control character. Only tabs and LF line breaks can be used."
BACKSLASH = 'A line can\'t end with "\\": Suricata would join it to the next line.'


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

    # OLD CODE START — NET-191 slice 3 review (S1): Suricata ends an option at every ";" without a
    # backslash before it, quotes or not, so these encoded a reading Suricata doesn't share
    # @pytest.mark.parametrize(
    #     "options",
    #     [
    #         'msg:"a; b"; content:"x"; sid:1000001;',
    #         'msg:"x"; content:"a;b|3b|"; sid:1000001;',
    #         r'msg:"a \"quoted\"; part"; content:"x"; sid:1000001;',
    #         r'msg:"escaped \; semicolon"; sid:1000001;',
    #     ],
    # )
    # def test_a_semicolon_inside_quotes_is_text(self, options):
    #     assert validate(rule(options)) == ([], 1)
    #
    # @pytest.mark.parametrize("word", sorted(FORBIDDEN))
    # def test_a_forbidden_word_inside_quotes_is_text(self, word):
    #     assert validate(rule(f'msg:"{word}: no"; content:"{word};"; sid:1000001;')) == (
    #         [],
    #         1,
    #     )
    # OLD CODE END

    @pytest.mark.parametrize(
        "options",
        [
            r'msg:"escaped \; semicolon"; sid:1000001;',
            r'content:"a\;b|3b|"; sid:1000001;',
            'msg:"a: b (c)"; content:"x"; sid:1000001;',
        ],
    )
    def test_an_escaped_semicolon_is_text(self, options):
        assert validate(rule(options)) == ([], 1)

    @pytest.mark.parametrize("word", sorted(FORBIDDEN))
    def test_a_forbidden_word_inside_an_option_value_is_text(self, word):
        content = rule(f'msg:"{word} no"; content:"{word}"; sid:1000001;')
        assert validate(content) == ([], 1)

    def test_the_sid_range_ends_are_allowed(self):
        rules = rule("sid:1000000;") + "\n" + rule("sid:1999999;")
        assert validate(rules) == ([], 2)

    def test_comments_and_blank_lines_are_not_rules(self):
        assert validate(f"# {rule('sid:5;')}\n\n{rule()}\n") == ([], 1)

    def test_tabs_are_fine(self):
        assert validate('alert\ttcp any any -> any any (msg:"x";\tsid:1000001;)') == (
            [],
            1,
        )


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

    # OLD CODE START — NET-191 slice 3 review (S1): with quotes ignored, 'b"' fails first
    # def test_a_keyword_after_a_quoted_semicolon_is_still_seen(self):
    #     error = only_error(rule('msg:"a;b"; lua:x.lua; sid:1000001;'))
    #     assert error["message"] == '"lua" can\'t be used in your own rules.'
    # OLD CODE END

    @pytest.mark.parametrize(
        "word",
        [
            "filemd5",
            "filesha1",
            "filesha256",
            "datajson",
            "tls_store",
            "tls.store",
            "TLS.Store",
        ],
    )
    def test_keywords_that_read_or_write_files(self, word):
        # S2: the file hash lists load any absolute path; tls.store is tls_store's alias
        error = only_error(rule(f'msg:"x"; {word}:list.txt; sid:1000001;'))
        assert error["message"] == f'"{word.lower()}" can\'t be used in your own rules.'

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
                "alert tcp any any -> any any (sid:1000001; rev:1)",
                'The last option must end with ";".',
            ),
            (
                'alert tcp any any -> any any (msg:"x\\)',
                'The last option must end with ";".',
            ),
            ("alert tcp any any -> any any (sid:1000001;", HEADER),
            ("alert tcp any any -> any any", HEADER),
            ("alert tcp [1.1.1.1, 2.2.2.2] any -> any any (sid:1000001;)", HEADER),
            (
                'alert tcp any any -> any any (msg:"x";; sid:1000001;)',
                'An option is empty (";;").',
            ),
            (
                "alert tcp any any -> any any (msg x; sid:1000001;)",
                '"msg x" is not an option name.',
            ),
        ],
    )
    def test_broken_rule_text(self, line, message):
        assert only_error(line)["message"] == message

    def test_errors_carry_their_line_numbers(self):
        content = "\n".join([rule(), rule(action="drop"), "", rule("sid:7;")])
        errors, count = validate(content)
        assert [e["line"] for e in errors] == [2, 4]
        assert count == 3


class TestSuricataReadsItTheSameWay:
    """S1/S4: each input here passed the first validator, and Suricata 8.0.7 then loaded "bypass"
    (checked with the Malcolm image's --engine-analysis), or the validator raised."""

    def test_a_quoted_semicolon_ends_the_option(self):
        line = rule('msg:"x"; metadata:a"; bypass; metadata:b"; sid:1000001; rev:1;')
        assert (
            only_error(line)["message"] == '"bypass" can\'t be used in your own rules.'
        )

    def test_a_second_opening_parenthesis(self):
        error = only_error(rule("(bypass; sid:1000001;"))
        assert error["message"] == 'The options start with one "(".'

    def test_a_nul_and_a_backslash_join_the_next_line(self):
        # Suricata stops the line at the NUL, sees it end in "\" and joins the "#" line to it
        content = (
            rule('msg:"x"; metadata:a\\\x00; sid:1000001;')
            + "\n#; bypass; sid:1000002;)\n"
        )
        assert validate(content)[0][0] == {"line": 1, "message": CONTROL}

    def test_a_carriage_return_hides_a_continued_line(self):
        content = (
            rule('msg:"x"; sid:1000001;')
            + "\r#x; metadata:a\\\n; bypass; sid:1000002;)\n"
        )
        assert validate(content)[0][0] == {"line": 1, "message": CONTROL}

    def test_options_after_the_seventh_header_field(self):
        # Suricata reads 7 header fields; the rest ("bypass; …") were its options
        line = 'alert tcp any any -> any any bypass; msg:"(x"; sid:1000001;)'
        assert only_error(line)["message"] == HEADER

    @pytest.mark.parametrize(
        "char",
        ["\x00", "\r", "\v", "\f", "\x1c", "\x1e", "\x7f", "\x85", " ", " "],
    )
    def test_each_line_break_python_or_suricata_sees_differently(self, char):
        assert validate(rule() + char + "x")[0][0]["message"] == CONTROL

    @pytest.mark.parametrize("line", [rule() + "\\", "# a note \\", rule() + "\\  "])
    def test_a_line_ending_in_a_backslash(self, line):
        assert only_error(line)["message"] == BACKSLASH

    def test_an_indented_line(self):
        # Suricata skips a line that starts with a space or tab; the editor would count it as a rule
        assert only_error("  " + rule())["message"].startswith(
            "Start each line at the left edge"
        )

    def test_a_line_longer_than_suricata_reads(self):
        # fgets reads 8 KiB: the rest of a longer line was read as a rule of its own (with bypass)
        head = 'alert tcp any any -> any any (msg:"x"; sid:1000001; metadata:'
        tail = "alert tcp any any -> any any (bypass; sid:1000002;)"
        line = head + "a" * (8191 - len(head) - 1) + ";" + tail
        assert only_error(line)["message"] == (
            "This line is over 8,190 bytes, the most Suricata reads as one rule."
        )

    @pytest.mark.parametrize("sid", ["²", "9" * 5000, "١" * 7])
    def test_sids_that_used_to_raise(self, sid):
        error = only_error(rule(f"sid:{sid};"))
        assert error["message"] == "The sid must be a number from 1000000 to 1999999."

    def test_a_lone_surrogate(self):
        assert validate(rule() + "\ud800") == (
            [
                {
                    "line": None,
                    "message": "Your rules contain text that isn't valid Unicode.",
                }
            ],
            0,
        )


class TestLimits:
    @staticmethod
    def _filled(size: int) -> str:
        """One rule, then comment lines (each under Suricata's line limit) up to `size` bytes."""
        text = rule()
        while len(text) < size:
            text += "\n#" + "x" * min(8000, size - len(text) - 2)
        return text

    def test_just_under_the_size_cap(self):
        content = self._filled(MAX_BYTES)
        assert len(content.encode()) == MAX_BYTES
        assert validate(content) == ([], 1)

    def test_just_over_the_size_cap(self):
        content = self._filled(MAX_BYTES + 1)
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


# OLD CODE START — NET-191 slice 3 review (S1): quotes no longer protect a ";"
# def test_split_options_keeps_quotes_and_escapes():
#     assert split_options(r'msg:"a;b"; content:"\"x\""; sid:1;') == [
#         'msg:"a;b"',
#         r'content:"\"x\""',
#         "sid:1",
#     ]
# OLD CODE END


def test_split_options_as_suricata():
    assert split_options(r'msg:"a;b"; content:"\"x\""; pcre:"/a\;b/"; sid:1;') == [
        'msg:"a',
        'b"',
        r'content:"\"x\""',
        r'pcre:"/a\;b/"',
        "sid:1",
    ]
