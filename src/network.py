import time
import asyncio
from curl_cffi import requests
from src.logger import log, fatal, warn
import src.config as config
import src.state as state
from src.proxies import ProxyManager

def init_session():
    state.session = requests.Session()
    state.session.impersonate = "chrome"
    # Separate lightweight session for Discord API/webhooks (no Roblox proxy).
    state.discord_session = requests.Session()
    try:
        state.discord_session.impersonate = "chrome"
    except Exception:
        pass
    state.proxy_mgr = ProxyManager()
    if state.proxy_mgr:
        proxy = state.proxy_mgr.get_proxy_dict()
        if proxy:
            state.session.proxies = proxy
            log(f"⚡ Chrome session initialized with proxy")
        else:
            log("⚡ Chrome session initialized")
    else:
        log("⚡ Chrome session initialized")


def get_roblox_proxies():
    # P1.2: rotating proxy per request (config-only: honors use_proxies/proxy_file).
    try:
        mgr = getattr(state, "proxy_mgr", None)
        if mgr:
            return mgr.get_proxy_dict_rotating()
    except Exception:
        pass
    return None

async def get_xcsrf(c: str) -> str:
    try:
        loop = asyncio.get_event_loop()
        px = get_roblox_proxies()
        r = await loop.run_in_executor(
            None,
            lambda: state.session.post(
                "https://auth.roblox.com/v2/logout",
                headers={
                    "Cookie": f"GuestData=UserID=-174948669; .ROBLOSECURITY={c}; RBXEventTrackerV2=CreateDate=11/19/2023 12:07:42 PM&rbxid=5189165742&browserid=200781876902;"
                },
                proxies=px,
            ),
        )
        return r.headers.get("x-csrf-token", "") or r.headers.get("X-CSRF-TOKEN", "")
    except Exception:
        return ""

async def get_user(c: str):
    try:
        loop = asyncio.get_event_loop()
        px = get_roblox_proxies()
        r = await loop.run_in_executor(
            None,
            lambda: state.session.get(
                "https://users.roblox.com/v1/users/authenticated",
                headers={
                    "Cookie": f"GuestData=UserID=-174948669; .ROBLOSECURITY={c}; RBXEventTrackerV2=CreateDate=11/19/2023 12:07:42 PM&rbxid=5189165742&browserid=200781876902;"
                },
                proxies=px,
            ),
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("name"), data.get("id")
    except Exception:
        pass
    return None, None

async def maybe_revalidate_full():
    """P8-C3: every 30min, test one full-marked cookie; revive if login works again.

    Config-only, best-effort, never raises. Prevents permanent loss when slots free up.
    """
    try:
        import time as _t
        now = _t.monotonic()
        if now - getattr(state, "_last_full_revalidate", 0.0) < state.FULL_REVALIDATE_INTERVAL:
            return
        mgr = getattr(state, "cookie_mgr", None)
        if not mgr or not getattr(mgr, "full_cookies", None):
            return
        async with state.cookie_switch_lock:
            if not mgr.full_cookies:
                return
            cand = next(iter(mgr.full_cookies))
        # I/O outside lock
        un, _uid = await get_user(cand)
        async with state.cookie_switch_lock:
            state._last_full_revalidate = now
            if un:
                try:
                    mgr.full_cookies.discard(cand)
                except Exception:
                    pass
                log(f"Revived cookie: {un} (slot freed)")
    except Exception:
        pass


async def switch_cookie() -> bool:
    # P0.1: loop instead of recursion — asyncio.Lock is not re-entrant,
    # so `return await switch_cookie()` inside the lock deadlocked forever.
    # NOTE: kept for manual `--switch` + startup display. Per-claim path uses
    # acquire_cookie_for_gid() below to avoid global thrash (P1.1).
    await maybe_revalidate_full()
    async with state.cookie_switch_lock:
        while True:
            if state.cookie_mgr.is_exhausted():
                from src.webhooks import send_all_cookies_exhausted_webhook
                fatal("ALL COOKIES EXHAUSTED")
                asyncio.create_task(send_all_cookies_exhausted_webhook())
                return False

            next_c = state.cookie_mgr.get_next()
            if not next_c:
                return False

            new_x = await get_xcsrf(next_c)
            if not new_x:
                warn("Failed to get XCSRF for next cookie, marking invalid")
                state.cookie_mgr.mark_full(next_c)
                continue

            uname, uid = await get_user(next_c)
            if not uname:
                warn("Failed to get User Info for next cookie, marking invalid")
                state.cookie_mgr.mark_full(next_c)
                continue

            state.cookie = next_c
            state.xcsrf = new_x
            state.username = uname
            state.userid = uid
            state.xcsrf_last_refresh = time.time()
            log(f"Switched to cookie: {uname}")
            return True

async def _set_xcsrf_locked(cookie: str, new_x: str):
    """Write XSRF only if `cookie` is still the active one (avoid clobbering after switch)."""
    async with state.xcsrf_lock:
        if cookie and cookie == state.cookie and new_x:
            state.xcsrf = new_x
            state.xcsrf_last_refresh = time.time()
            return True
        return False

async def xcsrf_refresher():
    while True:
        try:
            await asyncio.sleep(state.XCSRF_MAX_AGE / 2)
            if not state.cookie:
                continue
            cur = state.cookie
            new_x = await get_xcsrf(cur)
            if new_x:
                await _set_xcsrf_locked(cur, new_x)
        except asyncio.CancelledError:
            break
        except Exception as e:
            warn(f"XCSRF refresher error: {e}")

async def ensure_fresh_xcsrf():
    # P1.1: single-writer guard — skip refresh if another task just refreshed.
    async with state.xcsrf_lock:
        age = time.time() - state.xcsrf_last_refresh
        if age <= state.XCSRF_MAX_AGE or not state.cookie:
            return
        cur = state.cookie
    # Network I/O outside the lock to avoid blocking other claimers.
    new_x = await get_xcsrf(cur)
    if new_x:
        await _set_xcsrf_locked(cur, new_x)
    else:
        log(f"XCSRF refresh failed (age {age:.0f}s)")

def build_claim_headers(c: str, x: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Cookie": f"GuestData=UserID=-174948669; .ROBLOSECURITY={c}; RBXEventTrackerV2=CreateDate=11/19/2023 12:07:42 PM&rbxid=5189165742&browserid=200781876902;",
        "X-CSRF-TOKEN": x,
    }

def roblox_error_message(response) -> str:
    try:
        data = response.json()
        message = data.get("errors", [{}])[0].get("message", "")
        if message:
            return message.strip()
    except Exception:
        pass
    text = getattr(response, "text", "") or ""
    return text.strip()[:180]

def xcsrf_from_response(response) -> str:
    try:
        return response.headers.get("x-csrf-token", "") or response.headers.get("X-CSRF-TOKEN", "")
    except Exception:
        return ""

def is_xcsrf_invalid_response(response) -> bool:
    if not response or getattr(response, "status_code", 0) != 403:
        return False
    text = getattr(response, "text", "") or ""
    message = roblox_error_message(response)
    haystack = f"{message} {text}".lower()
    if "challenge" in haystack or "maximum" in haystack:
        return False
    return bool(xcsrf_from_response(response)) or any(
        marker in haystack
        for marker in ("xsrf token", "csrf token", "x-csrf-token", "token validation failed")
    )

async def refresh_xcsrf_for_cookie(c, response=None) -> bool:
    new_x = xcsrf_from_response(response) if response else ""
    if not new_x:
        new_x = await get_xcsrf(c)
    if not new_x:
        return False
    # Only overwrite global state if this cookie is still active.
    # Callers holding a snapshot (claimer) compare attempt_xcsrf vs state.xcsrf
    # to decide RETRY_XCSRF, so stale writes must not clobber a newer switch.
    if c == state.cookie:
        await _set_xcsrf_locked(c, new_x)
        return True
    # P1.1: also refresh matching lease token so per-GID retries see it.
    try:
        async with state.cookie_switch_lock:
            for _gid, _lease in list(getattr(state, "cookie_leases", {}).items()):
                if _lease.get("cookie") == c and new_x:
                    _lease["xcsrf"] = new_x
                    _lease["ts"] = time.time()
    except Exception:
        pass
    return True


async def acquire_cookie_for_gid(gid: int):
    """P1.1: lease one cookie for a gid (no global thrash).

    Reuses existing lease if still valid, else picks next available cookie.
    Returns dict {cookie,xcsrf,username,userid,ts} or None. Config-only.
    """
    mgr = getattr(state, "cookie_mgr", None)
    if not mgr:
        return None
    await maybe_revalidate_full()
    # Reuse valid lease
    async with state.cookie_switch_lock:
        try:
            ex = state.cookie_leases.get(gid)
            if ex and ex.get("cookie") not in getattr(mgr, "full_cookies", set()):
                return dict(ex)
        except Exception:
            pass
    total = 0
    try:
        total = len(mgr.cookies)
    except Exception:
        total = 0
    tried = 0
    # P8-C1: skip cookies already leased to other gids when stock remains.
    deferred: list = []
    while total <= 0 or tried < (total * 2):
        async with state.cookie_switch_lock:
            try:
                if mgr.is_exhausted():
                    return None
                cand = mgr.get_next()
            except Exception:
                return None
            if not cand:
                return None
            try:
                leased_by_others = {
                    l.get("cookie")
                    for g2, l in state.cookie_leases.items()
                    if g2 != gid and l.get("cookie")
                }
            except Exception:
                leased_by_others = set()
            if cand in leased_by_others and (tried < max(total - 1, 0)):
                if cand not in deferred:
                    deferred.append(cand)
                tried += 1
                continue
        nx = await get_xcsrf(cand)
        if not nx:
            async with state.cookie_switch_lock:
                try:
                    mgr.mark_full(cand)
                except Exception:
                    pass
            tried += 1
            continue
        un, uid = await get_user(cand)
        if not un:
            async with state.cookie_switch_lock:
                try:
                    mgr.mark_full(cand)
                except Exception:
                    pass
            tried += 1
            continue
        info = {"cookie": cand, "xcsrf": nx, "username": un, "userid": uid, "ts": time.time()}
        async with state.cookie_switch_lock:
            try:
                state.cookie_leases[gid] = dict(info)
            except Exception:
                pass
        # Best-effort display update (dashboard/--stats), not used for claim path.
        try:
            state.cookie = cand
            state.username = un
            state.userid = uid
        except Exception:
            pass
        try:
            await _set_xcsrf_locked(cand, nx)
        except Exception:
            pass
        return info
    return None


async def refresh_lease_xcsrf(gid: int, response=None) -> bool:
    """P1.1: refresh XSRF for the lease owning gid. Returns True if refreshed."""
    try:
        async with state.cookie_switch_lock:
            lease = state.cookie_leases.get(gid)
            c = lease.get("cookie") if lease else None
        if not c:
            return False
        ok = await refresh_xcsrf_for_cookie(c, response)
        if ok:
            # Re-read possibly updated token into lease
            async with state.cookie_switch_lock:
                try:
                    if gid in state.cookie_leases and state.cookie_leases[gid].get("cookie") == c:
                        if c == state.cookie and state.xcsrf:
                            state.cookie_leases[gid]["xcsrf"] = state.xcsrf
                            state.cookie_leases[gid]["ts"] = time.time()
                        elif response:
                            _nx = xcsrf_from_response(response)
                            if _nx:
                                state.cookie_leases[gid]["xcsrf"] = _nx
                                state.cookie_leases[gid]["ts"] = time.time()
                except Exception:
                    pass
        return ok
    except Exception:
        return False


async def ensure_fresh_lease_xcsrf(lease: dict):
    """P1.1: refresh lease token if older than XCSRF_MAX_AGE (config-only)."""
    try:
        age = time.time() - float(lease.get("ts", 0))
        if age <= state.XCSRF_MAX_AGE:
            return
        c = lease.get("cookie")
        if not c:
            return
        nx = await get_xcsrf(c)
        if nx:
            lease["xcsrf"] = nx
            lease["ts"] = time.time()
            try:
                async with state.cookie_switch_lock:
                    # sync back to stored lease if same cookie
                    for _gid, _l in list(state.cookie_leases.items()):
                        if _l.get("cookie") == c:
                            _l["xcsrf"] = nx
                            _l["ts"] = lease["ts"]
            except Exception:
                pass
    except Exception:
        pass


async def release_cookie_for_gid(gid: int):
    try:
        async with state.cookie_switch_lock:
            state.cookie_leases.pop(gid, None)
    except Exception:
        pass

def is_temporary_claim_error(message: str) -> bool:
    msg = (message or "").lower()
    return any(
        marker in msg
        for marker in ("temporarily unavailable", "try again later", "please try again", "operation is temporarily")
    )
