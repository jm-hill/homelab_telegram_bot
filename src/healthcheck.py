"""Docker HEALTHCHECK script. Exits 0 if healthy, 1 otherwise."""
import os
import sys
import urllib.request

port = os.environ.get('WEBHOOK_PORT', '8080')

try:
    resp = urllib.request.urlopen(f'http://localhost:{port}/health', timeout=5)
    sys.exit(0 if resp.status == 200 else 1)
except Exception:
    sys.exit(1)
