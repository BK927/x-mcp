import json
import os
import time

import pytest

from x_mcp.auth import parse_cookies, read_cookies, save_cookies
from x_mcp.errors import XError
from x_mcp.refs import collection_id, post_id, user_ref


def test_cookie_formats_only_keep_required_x_fields(tmp_path):
    expected = {"auth_token": "synthetic-a", "ct0": "synthetic-c"}
    formats = [
        json.dumps({**expected, "password": "discard"}),
        json.dumps(
            {
                "cookies": [
                    {"domain": ".x.com", "name": k, "value": v} for k, v in expected.items()
                ]
                + [{"domain": "other.test", "name": "secret", "value": "discard"}]
            }
        ),
        "# Netscape HTTP Cookie File\n#HttpOnly_.x.com\tTRUE\t/\tTRUE\t0\tauth_token\tsynthetic-a\n.x.com\tTRUE\t/\tTRUE\t0\tct0\tsynthetic-c\n",
    ]
    for value in formats:
        assert parse_cookies(value) == expected
    path = tmp_path / "private" / "session.json"
    save_cookies(path, expected)
    assert read_cookies(path) == expected
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "value",
    [
        {"auth_token": "one"},
        {"auth_token": "secret\r\ninjection", "ct0": "two"},
        [{"domain": "evil.x.com", "name": "auth_token", "value": "one"}],
        [{"domain": "x.com", "name": "auth_token", "value": "one", "expires": time.time() - 60}],
    ],
)
def test_bad_cookie_input_never_echoes_values(value):
    with pytest.raises(XError) as error:
        parse_cookies(json.dumps(value))
    assert error.value.code == "INVALID_SESSION"
    assert "injection" not in error.value.message


def test_references_do_not_enable_arbitrary_url_fetching():
    assert post_id("https://x.com/example/status/123?foo=bar") == "123"
    assert user_ref("https://twitter.com/Example") == "example"
    assert collection_id("https://x.com/i/communities/123", "community") == "123"
    for url in [
        "https://localhost/status/123",
        "https://x.com.evil.test/a/status/123",
        "https://user@x.com/a/status/123",
        "http://x.com/a/status/123",
        "https://x.com:bad/a/status/123",
    ]:
        with pytest.raises(XError):
            post_id(url)
