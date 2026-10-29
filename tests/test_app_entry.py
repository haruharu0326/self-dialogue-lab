"""The startup line must point the browser at an openable URL, not the bind address."""

from importlib.util import module_from_spec, spec_from_file_location
import io
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
    ('', 8501, 'http://127.0.0.1:8501/'),
    ('127.0.0.1', 18599, 'http://127.0.0.1:18599/'),
    ('::', 18599, 'http://localhost:18599/'),
    ('::1', 8501, 'http://localhost:8501/'),
    ('192.168.1.20', 9000, 'http://localhost:9000/'),
    ('myhost.local', 8501, 'http://localhost:8501/'),
])
def test_browser_url_only_uses_hosts_the_api_accepts(entry, host, port, expected):
    assert entry.browser_url(host, port) == expected


def test_public_url_wins_over_bind_address(entry):
    assert entry.browser_url('0.0.0.0', 8501, 'http://127.0.0.1:18080/') == 'http://127.0.0.1:18080/'
    assert entry.browser_url('0.0.0.0', 8501, ' http://127.0.0.1:18080/ ') == 'http://127.0.0.1:18080/'
    for blank in ('', '   ', None):
        assert entry.browser_url('0.0.0.0', 8501, blank) == 'http://127.0.0.1:8501/'


def test_hint_explains_wildcard_only_when_binding_all(entry):
    wildcard = entry.startup_hint('0.0.0.0', 8501)
    assert 'http://127.0.0.1:8501/' in wildcard and '0.0.0.0 は待ち受け用' in wildcard
    assert 'http://0.0.0.0' not in wildcard
    assert ':: は待ち受け用' in entry.startup_hint('::', 8501)
    assert entry.startup_hint('', 8501) == 'ブラウザでは http://127.0.0.1:8501/ を開いてください。'
    concrete = entry.startup_hint('127.0.0.1', 8501)
    assert concrete == 'ブラウザでは http://127.0.0.1:8501/ を開いてください。'


def test_unprintable_console_does_not_stop_startup(entry):
    ascii_only = io.TextIOWrapper(io.BytesIO(), encoding='ascii')
    entry.print_hint(entry.startup_hint('0.0.0.0', 8501), ascii_only)
    out = io.StringIO()
    entry.print_hint('ok', out)
    assert out.getvalue() == 'ok\n'
