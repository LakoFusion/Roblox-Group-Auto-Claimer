import asyncio
from typing import Optional, Set
from curl_cffi import requests

# State Variables
claimed_groups: Set[int] = set()
claiming_groups: Set[int] = set()
claim_state_lock = asyncio.Lock()
cookie_switch_lock = asyncio.Lock()
xcsrf_lock = asyncio.Lock()

# Negative cache: gid -> expire timestamp (monotonic time)
ignored_groups: dict = {}
IGNORED_TTL = 600.0  # 10 minutes for "has owner" groups

# Limit concurrent claim pipelines to avoid 429 stampede
claim_semaphore = asyncio.Semaphore(10)
# Bound inbound MESSAGE_CREATE fan-out (each message can contain many gids).
# P8-D1: sized generously (100) so slow 12s claims don't cause false burst drops;
# claim_semaphore(10) remains the real throttle.
inbound_semaphore = asyncio.Semaphore(100)

userid: Optional[int] = None
username: str = ""
cookie: str = ""
xcsrf: str = ""
xcsrf_last_refresh: float = 0
XCSRF_MAX_AGE: float = 180  # 3 minutes — refresh if older
discord_self_id: Optional[str] = None

session: requests.Session = None  # type: ignore[assignment]
discord_session: requests.Session = None  # type: ignore[assignment] separate session for Discord API/webhooks
stats = {"total": 0, "success": 0, "fail": 0}

# CookieManager instance
cookie_mgr = None
proxy_mgr = None

# P1.1: per-GID cookie lease to avoid global thrash across concurrent claims.
# gid -> {"cookie": str, "xcsrf": str, "username": str, "userid": int, "ts": float}
cookie_leases: dict = {}

# P8-C3: throttle for revalidating full-marked cookies (monotonic seconds)
_last_full_revalidate: float = 0.0
FULL_REVALIDATE_INTERVAL: float = 1800.0  # 30 minutes
_last_prune: float = 0.0

# Dashboard: circular recent-activity buffer (max 10) + live flag.
# When dashboard_live is True, emit() only buffers (renderer draws the screen).
recent_logs: list = []
dashboard_live: bool = False
