"""L0: protocol primitives — envelope, canonical JSON, hash baselines."""

import hashlib

import pytest

from novelos.protocol import (
    ErrorItem,
    canonical_json,
    combine_hash,
    envelope,
    hash_file,
    sha256_hex,
)

pytestmark = pytest.mark.l0


class TestEnvelope:
    def test_ok_true_implies_empty_errors(self):
        env = envelope({"x": 1})
        assert env["ok"] is True
        assert env["errors"] == []
        assert env["data"] == {"x": 1}

    def test_errors_imply_ok_false(self):
        env = envelope(None, [ErrorItem("X_CODE", "boom")])
        assert env["ok"] is False
        assert env["errors"] == [{"code": "X_CODE", "message": "boom"}]

    def test_none_path_and_hint_dropped(self):
        env = envelope(None, [ErrorItem("X_CODE", "m", path=None, hint=None)])
        assert "path" not in env["errors"][0]
        assert "hint" not in env["errors"][0]

    def test_path_and_hint_kept(self):
        env = envelope(None, [ErrorItem("X_CODE", "m", path="a.yaml", hint="fix it")])
        assert env["errors"][0]["path"] == "a.yaml"
        assert env["errors"][0]["hint"] == "fix it"


class TestCanonicalJson:
    def test_byte_stable_across_key_order(self):
        a = canonical_json({"b": 1, "a": [1, 2], "n": None})
        b = canonical_json({"n": None, "a": [1, 2], "b": 1})
        assert a == b
        assert a == b'{"a":[1,2],"b":1,"n":null}'

    def test_float_rejected(self):
        with pytest.raises(TypeError):
            canonical_json({"v": 1.5})
        with pytest.raises(TypeError):
            canonical_json([{"deep": [0, 1.0]}])


class TestHashing:
    def test_sha256_hex_form(self):
        assert sha256_hex(b"") == "sha256:" + hashlib.sha256(b"").hexdigest()

    def test_hash_file_raw_bytes(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"\x00\r\n\xff")
        assert hash_file(p) == sha256_hex(b"\x00\r\n\xff")


class TestCombineHash:
    def test_order_independent(self):
        h1 = "sha256:" + "a" * 64
        h2 = "sha256:" + "b" * 64
        forward = combine_hash([("ch-01/text.md", h1), ("premise.md", h2)])
        reversed_ = combine_hash([("premise.md", h2), ("ch-01/text.md", h1)])
        assert forward == reversed_

    def test_fixed_vector_two_space_separator(self):
        h1 = "sha256:" + "1" * 64
        h2 = "sha256:" + "2" * 64
        expected_text = f"{h1}  a.md\n{h2}  b.md\n"
        assert combine_hash([("b.md", h2), ("a.md", h1)]) == sha256_hex(expected_text.encode("utf-8"))

    def test_sorted_by_path_bytes(self):
        h = "sha256:" + "0" * 64
        # "Z" (0x5A) sorts before "a" (0x61) in byte order
        expected_text = f"{h}  Z.md\n{h}  a.md\n"
        assert combine_hash([("a.md", h), ("Z.md", h)]) == sha256_hex(expected_text.encode("utf-8"))

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            combine_hash([])
