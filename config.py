"""Configuration for the Y Combinator Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT                port the API listens on (default 8000)
    YCOMBINATOR_PROXY   proxy URL for every request, e.g. http://user:pass@host:port
                        (default: none — direct). ycombinator.com runs no bot
                        protection, so you very likely don't need this. Set it
                        only if you start seeing 403 / 429 answers at high volume.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

YCOMBINATOR_PROXY = os.environ.get("YCOMBINATOR_PROXY") or None

# After a 403 / 429, new sessions switch to the fallback proxy for this long.
YCOMBINATOR_BLOCK_COOLDOWN = 900


def ycombinator_proxy():
    """The proxy every session uses (None = direct)."""
    return os.environ.get("YCOMBINATOR_PROXY") or None


def ycombinator_fallback_proxy():
    """The proxy a session moves to after a block (None = stay direct)."""
    return os.environ.get("YCOMBINATOR_PROXY") or None
