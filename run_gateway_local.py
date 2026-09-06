"""Boot the gateway locally against the real LEARN database.

Reads .env.learn (gitignored) so the DSN never goes on a command line, then serves on
loopback only — a Cloudflare Tunnel is what gives it a public origin, not a bound port.
"""
import io, os

for line in io.open(".env.learn", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

os.environ.setdefault("WINNY_CRED_KEY", "dev-only-ephemeral-key-for-local-boot")

import uvicorn
from winny_gateway.app import create_app

if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=8000, log_level="warning")
