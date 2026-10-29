"""Product entry point: serve the API and the built React screen on one local port."""
import os

import uvicorn

from self_dialogue_lab.api import create_app

_WILDCARD_HOSTS = {'0.0.0.0', '::', ''}


def browser_url(host, port, public_url=None):
    """Return the URL to open in a browser; uvicorn logs the bind address, which may be a wildcard."""
    if public_url:
        return public_url
    if host in _WILDCARD_HOSTS:
        return f'http://127.0.0.1:{port}/'
    return f'http://[{host}]:{port}/' if ':' in host else f'http://{host}:{port}/'


def startup_hint(host, port, public_url=None):
    """One line for stdout; only the URL is shown, never secrets or DB paths."""
    line = f'ブラウザでは {browser_url(host, port, public_url)} を開いてください。'
    if host in _WILDCARD_HOSTS:
        line += f'（ログの {host or "0.0.0.0"} は待ち受け用のアドレスで、ブラウザでは開けません）'
    return line


if __name__ == '__main__':
    host = os.environ.get('SELF_DIALOGUE_HOST', '127.0.0.1')
    port = int(os.environ.get('SELF_DIALOGUE_PORT', '8501'))
    print(startup_hint(host, port, os.environ.get('SELF_DIALOGUE_PUBLIC_URL')), flush=True)
    # Access logs are off so request paths and timing never become a business log.
    uvicorn.run(create_app(), host=host, port=port, access_log=False)
