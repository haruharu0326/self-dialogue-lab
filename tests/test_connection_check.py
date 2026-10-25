from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest


def load_check():
    path = Path(__file__).resolve().parents[1]/'scripts/check_gemini.py'
    spec = spec_from_file_location('connection_check', path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('network_error', [False, True])
def test_diagnostic_redacts_key_proxy_and_remote_messages(monkeypatch, capsys, network_error):
    check = load_check()
    monkeypatch.setenv('GEMINI_API_KEY', 'test-secret-key')
    monkeypatch.setenv('GEMINI_MODEL', 'gemini-test')
    monkeypatch.setattr(check, 'getproxies', lambda: {'https': 'http://name:proxy-secret@example.invalid'})
    def send(req, timeout):
        assert b'test-secret-key' not in (req.data or b'')
        if network_error:
            raise URLError('private reason test-secret-key')
        body = b'{"error":{"status":"PERMISSION_DENIED","message":"test-secret-key private message","details":[{"reason":"API_KEY_INVALID"}]}}'
        raise HTTPError(req.full_url, 403, 'private message', {}, BytesIO(body))
    assert check.run(send) == 1
    output = capsys.readouterr().out
    assert 'test-secret-key' not in output
    assert 'proxy-secret' not in output and 'private' not in output
    assert ('Network error type:' if network_error else 'PERMISSION_DENIED') in output


def test_diagnostic_missing_key_does_not_send(monkeypatch, capsys):
    check = load_check()
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError('No request expected')
    assert check.run(forbidden) == 2
    assert 'API key configured: False' in capsys.readouterr().out


def test_metadata_check_does_not_generate_text(monkeypatch, capsys):
    check = load_check()
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    monkeypatch.setenv('GEMINI_MODEL', 'gemini-test')
    calls = []
    def send(req, timeout):
        calls.append(req.get_method())
        assert timeout == 15
        response = BytesIO(b'{"name":"models/gemini-test"}')
        response.status = 200
        return response
    assert check.run(send) == 0
    assert calls == ['GET']
    assert 'not attempted' in capsys.readouterr().out


def test_generation_uses_extended_timeout_after_metadata_passes(monkeypatch, capsys):
    check = load_check()
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    monkeypatch.setenv('GEMINI_MODEL', 'gemini-test')
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS', '120')
    calls = []
    def send(req, timeout):
        calls.append(req.get_method())
        if req.get_method() == 'GET':
            response = BytesIO(b'{"name":"models/gemini-test"}')
        else:
            assert timeout == 120
            raise TimeoutError('secret remote detail')
        response.status = 200
        return response
    assert check.run(send, generate=True) == 1
    assert calls == ['GET', 'POST']
    output = capsys.readouterr().out
    assert 'TimeoutError' in output and 'secret remote' not in output
