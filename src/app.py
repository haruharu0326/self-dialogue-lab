"""Product entry point: serve the API and the built React screen on one local port."""
import os

import uvicorn

from self_dialogue_lab.api import create_app

if __name__ == '__main__':
    # Access logs are off so request paths and timing never become a business log.
    uvicorn.run(create_app(), host=os.environ.get('SELF_DIALOGUE_HOST', '127.0.0.1'),
                port=int(os.environ.get('SELF_DIALOGUE_PORT', '8501')), access_log=False)
