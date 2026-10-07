import json

from pricedin import config
from pricedin.data import archive


def test_identical_bodies_are_stored_once_and_every_fetch_is_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEDIN_RAW_DIR", str(tmp_path))
    archive.store("sec/x", "https://example.test/x", b'{"a": 1}')
    archive.store("sec/x", "https://example.test/x", b'{"a": 1}')
    archive.store("sec/x", "https://example.test/x", b'{"a": 2}')

    folder = config.raw_dir() / "sec/x"
    assert len(list(folder.glob("*.json"))) == 2
    assert len((folder / archive.MANIFEST).read_text().splitlines()) == 3

    body, entry = archive.latest("sec/x")
    assert json.loads(body) == {"a": 2}
    assert entry["bytes"] == len(b'{"a": 2}')


def test_latest_is_none_before_any_fetch(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEDIN_RAW_DIR", str(tmp_path))
    assert archive.latest("sec/nothing") is None
