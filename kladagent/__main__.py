"""Start the website: python -m kladagent"""
import logging

from .app import create_app
from .config import load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "httpx2", "anthropic"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

settings = load_settings()
print(f"\n  Klädagenten körs på http://{settings.host}:{settings.port}\n")
create_app(settings).run(host=settings.host, port=settings.port, threaded=True)
