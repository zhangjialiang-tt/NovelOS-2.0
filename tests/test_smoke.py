import json

import pytest

pytestmark = pytest.mark.l0


def test_package_smoke(capsys):
    import novelos
    from novelos.cli import main

    assert novelos.__version__ == "0.1.0"
    assert main(["version", "--json"]) == 0
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is True
    assert env["data"]["core_version"] == "0.1.0"
    assert env["data"]["protocol_version"] == "1.0"
