"""Used by the Docker HEALTHCHECK instruction.

Exit code 0 => healthy, 1 => unhealthy. Written in Python because the slim
base image has no curl/wget.
"""
import os
import sys
import urllib.request

url = "http://127.0.0.1:%s/health" % os.getenv("PORT", "5000")
try:
    with urllib.request.urlopen(url, timeout=2) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception:  # HTTPError (503), connection refused, timeout ...
    sys.exit(1)
