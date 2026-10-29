"""The startup line must point the browser at an openable URL, not the bind address."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


@pytest.fixture
def entry():
    spec = spec_from_file_location('app_entry', Path(__file__).resolve().parents[1] / 'src/app.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('host,port,expected', [
    ('0.0.0.0', 8501, 'http://127.0.0.1:8501/'),
    ('::', 18599, 'http://127.0.0.1:18599/'),
    ('127.0.0.1', 8501, 'http://127.0.0.1:8501/'),
    ('192.168.1.20', 9000, 'http://192.168.1.20:9000/'),
    ('::1', 8501, 'http://[::1]:8501/'),
])
def test_browser_url_replaces_wildcard_and_keeps_concrete_host(entry, host, port, expected):
    assert entry.browser_url(host, port) == expected


def test_public_url_wins_over_bind_address(entry):
    assert entry.browser_url('0.0.0.0', 8501, 'http://127.0.0.1:18080/') == 'http://127.0.0.1:18080/'
    assert entry.browser_url('0.0.0.0', 8501, '') == 'http://127.0.0.1:8501/'


def test_hint_explains_wildcard_only_when_binding_all(entry):
    wildcard = entry.startup_hint('0.0.0.0', 8501)
    assert 'http://127.0.0.1:8501/' in wildcard and '0.0.0.0 は待ち受け用' in wildcard
    assert 'http://0.0.0.0' not in wildcard
    assert ':: は待ち受け用' in entry.startup_hint('::', 8501)
    concrete = entry.startup_hint('127.0.0.1', 8501)
    assert concrete == 'ブラウザでは http://127.0.0.1:8501/ を開いてください。'
