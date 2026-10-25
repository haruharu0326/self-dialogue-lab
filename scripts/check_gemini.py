"""Run inside the container via stdin. Never read the DB or print credentials."""

from http.client import HTTPException
import json
import os
import re
import math
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, getproxies

from self_dialogue_lab.gemini import GeminiError, GeminiResponder, _NoRedirect


def run(transport=None, generate=False):
    key = os.environ.get('GEMINI_API_KEY', '')
    print('API key configured:', bool(key.strip()))
    proxies = getproxies()
    print('HTTP proxy configured:', bool(proxies.get('http')))
    print('HTTPS proxy configured:', bool(proxies.get('https')))
    if not key.strip():
        print('Result: missing key in the running container; recreate it after saving .env.')
        return 2
    send = transport or build_opener(_NoRedirect()).open
    try:
        generation_timeout = float(os.environ.get('GEMINI_TIMEOUT_SECONDS', '120'))
        if not math.isfinite(generation_timeout) or not 5 <= generation_timeout <= 300:
            raise ValueError('invalid timeout')
    except ValueError:
        print('Result: invalid GEMINI_TIMEOUT_SECONDS; use 5 through 300.')
        return 2

    def checked_send(request, timeout):
        start = time.monotonic()
        effective_timeout = generation_timeout if request.get_method() == 'POST' else 15
        print('Phase:', 'text-generation POST' if request.get_method() == 'POST' else 'model-info GET', flush=True)
        try:
            response = send(request, timeout=effective_timeout)
            print('HTTP status:', response.status)
            print('Response headers received in seconds:', round(time.monotonic() - start, 1))
            return response
        except HTTPError as error:
            print('HTTP status:', error.code)
            try:
                details = json.loads(error.read(65536)).get('error', {})
                status = details.get('status', '')
                if isinstance(status, str) and re.fullmatch(r'[A-Z_]{1,80}', status):
                    print('Google error status:', status)
                for item in details.get('details', []):
                    reason = item.get('reason', '')
                    if isinstance(reason, str) and re.fullmatch(r'[A-Z_]{1,100}', reason):
                        print('Google error reason:', reason)
                    for violation in item.get('fieldViolations', []):
                        field = violation.get('field', '')
                        if isinstance(field, str) and re.fullmatch(r'[a-zA-Z0-9_.\[\]-]{1,160}', field):
                            print('Invalid request field:', field)
            except (ValueError, TypeError, AttributeError, OSError):
                pass
            raise
        except URLError as error:
            print('Network error type:', type(error.reason).__name__)
            print('Elapsed seconds:', round(time.monotonic() - start, 1))
            print('Result: request did not reach a usable API response.')
            raise
        except (TimeoutError, OSError, HTTPException) as error:
            print('Network error type:', type(error).__name__)
            print('Elapsed seconds:', round(time.monotonic() - start, 1))
            raise

    client = GeminiResponder(api_key=key, transport=checked_send)
    valid_model = bool(re.fullmatch(r'gemini-[a-zA-Z0-9._-]+', client.model))
    print('Model setting valid:', valid_model)
    if not valid_model:
        return 2
    lookup = Request(f'https://generativelanguage.googleapis.com/v1beta/models/{client.model}',
                     headers={'x-goog-api-key': key}, method='GET')
    try:
        with checked_send(lookup, timeout=15) as response:
            metadata = json.loads(response.read(65536))
        if not isinstance(metadata.get('name'), str) or not re.fullmatch(r'models/gemini-[a-zA-Z0-9._-]+', metadata['name']):
            raise ValueError('invalid model metadata')
    except (HTTPError, URLError, OSError, HTTPException, ValueError, AttributeError, TypeError):
        print('Model lookup failed. Text generation was not attempted.')
        return 1
    print('Model lookup: passed.')
    if not generate:
        print('Text generation: not attempted (metadata check only).')
        return 0
    print('Generation wait limit in seconds:', generation_timeout, flush=True)
    try:
        client.respond('Connection test. Please reply with a brief greeting.', 'connection check', [], history=[], demo=True)
    except GeminiError:
        print('Application result: no validated response. No conversation was saved.')
        return 1
    print('Application result: Gemini response received and validated. No conversation was saved.')
    return 0


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Check model access without exposing secrets')
    parser.add_argument('--generate', action='store_true', help='also send one synthetic generation request')
    args = parser.parse_args()
    raise SystemExit(run(generate=args.generate))
