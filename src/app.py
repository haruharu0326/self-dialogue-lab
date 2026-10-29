"""Product entry point: serve the API and the built React screen on one local port."""
import os
import sys

import uvicorn

from self_dialogue_lab.api import create_app

_IPV4_ANY = {'0.0.0.0', ''}


def browser_url(host, port, public_url=None):
    """Return a URL that passes the API Host check (127.0.0.1 / localhost), not the bind address."""
    public_url = (public_url or '').strip()
    if public_url:
        return public_url
    if host in _IPV4_ANY or host == '127.0.0.1':
        return f'http://127.0.0.1:{port}/'
    # '::' listens on IPv6 only, and other hosts would be refused by the Host check.
    return f'http://localhost:{port}/'


def startup_hint(host, port, public_url=None):
    """One line for stdout; only the URL is shown, never secrets or DB paths."""
    line = f'ブラウザでは {browser_url(host, port, public_url)} を開いてください。'
    if host in ('0.0.0.0', '::'):
        line += f'（ログの {host} は待ち受け用のアドレスで、ブラウザでは開けません）'
    return line


def print_hint(line, stream=None):
    """The hint is a convenience; an unprintable console must not stop the server."""
    try:
        print(line, file=stream or sys.stdout, flush=True)
    except (UnicodeError, OSError, ValueError):
        pass


if __name__ == '__main__':
    host = os.environ.get('SELF_DIALOGUE_HOST', '127.0.0.1')
    port = int(os.environ.get('SELF_DIALOGUE_PORT', '8501'))
    print_hint(startup_hint(host, port, os.environ.get('SELF_DIALOGUE_PUBLIC_URL')))
    # Access logs are off so request paths and timing never become a business log.
    uvicorn.run(create_app(), host=host, port=port, access_log=False)
