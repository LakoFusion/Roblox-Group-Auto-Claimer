import time
import asyncio
import random
from datetime import datetime, timezone
import src.config as config
import src.state as state
from src.logger import warn, fatal, log, ok, fmt_ms, fmt_num, footer_text
from src.network import refresh_xcsrf_for_cookie, is_xcsrf_invalid_response, roblox_error_message, is_temporary_claim_error
from src.webhooks import send_claim_error_webhook, send_account_full_webhook

async def handle_claim_errors(
    gid: int,
    jr,
    cr,
    account_cookie=None,
    account_xcsrf=None,
    account_username=None,
    account_userid=None,
) -> str:
    account_cookie = account_cookie or state.cookie
    account_xcsrf = account_xcsrf or state.xcsrf
    account_username = account_username or state.username
    account_userid = account_userid or state.userid
    error_reason = f"JOIN: {jr.status_code} | CLAIM: {cr.status_code}"
    retry_status = config.CLAIM_FAILED
    should_leave_group = True

    # P8-E1: 401 = dead/invalid cookie → mark full + retry new account.
    if jr.status_code == 401 or cr.status_code == 401:
        warn(f"{gid} - Cookie unauthorized (401), marking invalid & switching account")
        error_reason = "Cookie unauthorized (401)"
        try:
            async with state.cookie_switch_lock:
                state.cookie_mgr.mark_full(account_cookie)
        except Exception:
            try:
                state.cookie_mgr.mark_full(account_cookie)
            except Exception:
                pass
        return config.CLAIM_RETRY_COOKIE

    if jr.status_code == 403:
        if is_xcsrf_invalid_response(jr):
            warn(f"{gid} - JOIN XCSRF invalid, refreshing token")
            should_leave_group = False
            if await refresh_xcsrf_for_cookie(account_cookie, jr):
                return config.CLAIM_RETRY_XCSRF
            error_reason = "Invalid XCSRF token"
        try:
            msg = jr.json().get("errors", [{}])[0].get("message", "").lower()
            if "maximum" in msg:
                warn(f"Account full: {account_username} ({account_userid})")
                # P1.1: mark under switch lock to avoid racing get_next() handing
                # out this same cookie to another gid concurrently.
                try:
                    async with state.cookie_switch_lock:
                        state.cookie_mgr.mark_full(account_cookie)
                except Exception:
                    try:
                        state.cookie_mgr.mark_full(account_cookie)
                    except Exception:
                        pass
                asyncio.create_task(
                    send_account_full_webhook(
                        account_username,
                        account_userid,
                        state.cookie_mgr.available_count(),
                        len(state.cookie_mgr.cookies),
                    )
                )
                return config.CLAIM_RETRY_COOKIE
            if "challenge" in msg:
                warn(f"{gid} - Challenge required, switching account")
                return config.CLAIM_RETRY_COOKIE
        except Exception:
            pass
    elif jr.status_code == 429:
        warn(f"{gid} - Join rate limited, switching account")
        return config.CLAIM_RETRY_COOKIE

    # Handle CLAIM errors
    if cr.status_code == 403:
        if is_xcsrf_invalid_response(cr):
            warn(f"{gid} - CLAIM XCSRF invalid, refreshing token")
            should_leave_group = False
            if await refresh_xcsrf_for_cookie(account_cookie, cr):
                return config.CLAIM_RETRY_XCSRF
            error_reason = "Invalid XCSRF token"
        else:
            msg = roblox_error_message(cr)
            msg_lower = msg.lower()
            if "owner" in msg_lower and ("already" in msg_lower or "has" in msg_lower):
                error_reason = "Group has owner"
                # P2: negative cache — don't recount / re-request this gid for a while
                try:
                    import time as _t
                    async with state.claim_state_lock:
                        state.ignored_groups[gid] = _t.monotonic() + state.IGNORED_TTL
                except Exception:
                    pass
            elif msg:
                error_reason = msg
                if is_temporary_claim_error(msg):
                    should_leave_group = False
            else:
                error_reason = "CLAIM forbidden"

    elif cr.status_code == 500:
        msg = roblox_error_message(cr)
        error_reason = msg or "CLAIM server error (500)"

    elif cr.status_code == 429:
        warn(f"{gid} - Rate limited, switching account")
        error_reason = "Rate limited (CLAIM)"
        retry_status = config.CLAIM_RETRY_COOKIE

    # P8-C2: retry with a NEW account → free this lease's slot async (fire-and-forget
    # with snapshot creds). Same-account XSRF retry keeps should_leave=False path below.
    if retry_status != config.CLAIM_FAILED:
        if retry_status == config.CLAIM_RETRY_COOKIE and jr.status_code == 200:
            asyncio.create_task(
                leave_group(gid, account_cookie, account_xcsrf, account_userid)
            )
        return retry_status

    if jr.status_code == 200 and should_leave_group:
        asyncio.create_task(
            leave_group(gid, account_cookie, account_xcsrf, account_userid)
        )

    if retry_status == config.CLAIM_FAILED:
        warn(f"{gid} - {error_reason}")
        asyncio.create_task(
            send_claim_error_webhook(gid, error_reason, jr.status_code, cr.status_code)
        )

    return retry_status

async def _still_active(gid: int) -> bool:
    async with state.claim_state_lock:
        return gid in state.claiming_groups or gid in state.claimed_groups


async def _prune_ignored():
    # P8-D3: time-based prune (60s) + size guard, cheap per call.
    try:
        import time as _t
        now = _t.monotonic()
        if now - getattr(state, "_last_prune", 0.0) < 60.0 and len(state.ignored_groups) <= 200:
            return
        async with state.claim_state_lock:
            for k in [k for k, exp in state.ignored_groups.items() if exp <= now]:
                state.ignored_groups.pop(k, None)
            state._last_prune = now
    except Exception:
        pass


async def set_group_status(gid: int, account_cookie=None, account_xcsrf=None):
    # P0.2: orphan guard — skip PATCH if handle_claim already timed out/discarded.
    if not await _still_active(gid):
        return
    account_cookie = account_cookie or state.cookie
    account_xcsrf = account_xcsrf or state.xcsrf
    try:
        messages = ["Catch me if you can!", " Ultra Fusion"]
        loop = asyncio.get_event_loop()
        if not await _still_active(gid):
            return
        from src.network import get_roblox_proxies
        _px = get_roblox_proxies()
        await loop.run_in_executor(
            None,
            lambda: state.session.patch(
                f"https://groups.roblox.com/v1/groups/{gid}/status",
                headers={
                    "Cookie": f"GuestData=UserID=-174948669; .ROBLOSECURITY={account_cookie}; RBXEventTrackerV2=CreateDate=11/19/2023 12:07:42 PM&rbxid=5189165742&browserid=200781876902;",
                    "X-CSRF-TOKEN": account_xcsrf,
                },
                json={"message": random.choice(messages)},
                proxies=_px,
            ),
        )
    except Exception:
        pass

async def leave_group(gid: int, account_cookie=None, account_xcsrf=None, account_userid=None):
    account_cookie = account_cookie or state.cookie
    account_xcsrf = account_xcsrf or state.xcsrf
    account_userid = account_userid or state.userid
    try:
        headers = {
            "Cookie": f"GuestData=UserID=-174948669; .ROBLOSECURITY={account_cookie}; RBXEventTrackerV2=CreateDate=11/19/2023 12:07:42 PM&rbxid=5189165742&browserid=200781876902;",
            "X-CSRF-TOKEN": account_xcsrf,
        }
        loop = asyncio.get_event_loop()
        try:
            from src.network import get_roblox_proxies as _getpx
            _px_leave = _getpx()
        except Exception:
            _px_leave = None
        r = await loop.run_in_executor(
            None,
            lambda: state.session.delete(
                f"https://groups.roblox.com/v1/groups/{gid}/users/{account_userid}",
                headers=headers,
                proxies=_px_leave,
            ),
        )
        if r.status_code == 200:
            log(f"Left group {gid}")
    except Exception:
        pass

async def check_group_value(
    gid: int,
    total_ms: float = 0,
    join_ms: float = 0,
    claim_ms: float = 0,
    delay: float = 0,
    method="Sequential",
    account_cookie=None,
    account_xcsrf=None,
    account_username=None,
):
    account_cookie = account_cookie or state.cookie
    account_xcsrf = account_xcsrf or state.xcsrf
    account_username = account_username or state.username
    try:
        headers = {
            "Cookie": f"GuestData=UserID=-174948669; .ROBLOSECURITY={account_cookie}; RBXEventTrackerV2=CreateDate=11/19/2023 12:07:42 PM&rbxid=5189165742&browserid=200781876902;",
            "X-CSRF-TOKEN": account_xcsrf,
        }

        loop = asyncio.get_event_loop()

        def retry_request(url, req_headers=None, max_retries=3):
            for attempt in range(max_retries):
                try:
                    try:
                        from src.network import get_roblox_proxies as _getpx2
                        _pxg = _getpx2()
                    except Exception:
                        _pxg = None
                    r = (
                        state.session.get(url, headers=req_headers, proxies=_pxg)
                        if req_headers
                        else state.session.get(url, proxies=_pxg)
                    )
                    if r.status_code == 200:
                        return r.json(), 200
                    elif r.status_code == 429:
                        time.sleep((attempt + 1) * 2)
                        continue
                    else:
                        return None, r.status_code
                except:
                    if attempt < max_retries - 1:
                        time.sleep(2)
            return None, 0

        robux, pending, games_count, visits, clothing = 0, 0, 0, 0, 0
        thumbnail, members, group_name = None, 0, f"Group {gid}"

        data, _ = await loop.run_in_executor(
            None, lambda: retry_request(f"https://groups.roblox.com/v1/groups/{gid}")
        )
        if data:
            group_name = data.get("name", group_name)
            members = data.get("memberCount", 0)

        data, _ = await loop.run_in_executor(
            None,
            lambda: retry_request(
                f"https://games.roblox.com/v2/groups/{gid}/gamesV2?accessFilter=2&limit=100&sortOrder=Asc"
            ),
        )
        if data:
            games_list = data.get("data", [])
            games_count = len(games_list)
            visits = sum(g.get("placeVisits", 0) for g in games_list)

        data, _ = await loop.run_in_executor(
            None,
            lambda: retry_request(
                f"https://economy.roblox.com/v1/groups/{gid}/currency", headers
            ),
        )
        if data:
            robux = data.get("robux", 0)

        data, _ = await loop.run_in_executor(
            None,
            lambda: retry_request(
                f"https://economy.roblox.com/v1/groups/{gid}/revenue/summary/Year",
                headers,
            ),
        )
        if data:
            pending = data.get("pendingRobux", 0)

        data, _ = await loop.run_in_executor(
            None,
            lambda: retry_request(
                f"https://catalog.roblox.com/v1/search/items/details?Category=3&SortType=Relevance&CreatorTargetId={gid}&ResultsPerPage=100&CreatorType=2"
            ),
        )
        if data:
            clothing = len(data.get("data", []))
            next_cursor = data.get("nextPageCursor")
            while next_cursor:
                page_data, _ = await loop.run_in_executor(
                    None,
                    lambda nc=next_cursor: retry_request(
                        f"https://catalog.roblox.com/v1/search/items/details?Category=3&SortType=Relevance&CreatorTargetId={gid}&ResultsPerPage=100&CreatorType=2&Cursor={nc}"
                    ),
                )
                if page_data:
                    clothing += len(page_data.get("data", []))
                    next_cursor = page_data.get("nextPageCursor")
                else:
                    break

        data, _ = await loop.run_in_executor(
            None,
            lambda: retry_request(
                f"https://thumbnails.roblox.com/v1/groups/icons?groupIds={gid}&size=150x150&format=Png&isCircular=false"
            ),
        )
        if data and data.get("data"):
            thumbnail = data["data"][0].get("imageUrl")

        log(f"📊 {group_name} | 💰{robux:,} | ⏳{pending:,} | 🎮{games_count} | 👁️{visits:,} | 👕{clothing} | 👥{members:,}")

        is_high_value = any([robux >= 100, pending >= 100, games_count >= 5, visits >= 1000, clothing >= 10])

        embed = {
            "username": config.EMBED_NAME,
            "embeds": [
                {
                    "author": {"name": f"{config.APP_NAME} • CLAIMED"},
                    "title": f"{'💎' if is_high_value else '✅'} {group_name} ({gid})",
                    "description": (
                        f"⚡ Total Speed: **{fmt_ms(total_ms)}** (JOIN {fmt_ms(join_ms)} | CLAIM {fmt_ms(claim_ms)})\n"
                        f"👤 Claimer: **{account_username}**"
                    ),
                    "url": f"https://roblox.com/groups/{gid}",
                    "fields": [
                        {
                            "name": "💰 Economy",
                            "value": (
                                f"Balance: **{fmt_num(robux)} Robux**\n"
                                f"Pending: **{fmt_num(pending)} Robux**\n"
                                f"Clothing: **{clothing} items**"
                            ),
                            "inline": True,
                        },
                        {
                            "name": "🎮 Assets & Community",
                            "value": (
                                f"Games: **{games_count} experiences**\n"
                                f"Visits: **{fmt_num(visits)} total**\n"
                                f"Members: **{fmt_num(members)} members**"
                            ),
                            "inline": True,
                        },
                    ],
                    "thumbnail": {"url": thumbnail} if thumbnail else {},
                    "color": config.COLOR_GOLD if is_high_value else config.COLOR_SUCCESS,
                    "footer": {"text": footer_text()},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }

        # P2: orphan guard — if handle_claim already timed out and discarded
        # `claiming`, this success arrived too late; don't send duplicate ✅.
        async with state.claim_state_lock:
            still_active = gid in state.claiming_groups or gid in state.claimed_groups
        if not still_active:
            return

        await loop.run_in_executor(
            None,
            lambda: (getattr(state, "discord_session", None) or state.session).post(
                config.webhooks["detections"], json=embed
            ),
        )

        if is_high_value:
            ok(f"💎 High value group: {group_name}")

    except Exception as e:
        pass

async def handle_claim(gid: int):
    """Main claim handler with in-flight protection and retry-friendly state."""
    # P0.2: opportunistic prune (cheap, no extra task)
    await _prune_ignored()
    async with state.claim_state_lock:
        import time as _t
        exp = state.ignored_groups.get(gid)
        if exp and _t.monotonic() < exp:
            return
        elif exp:
            state.ignored_groups.pop(gid, None)
        if gid in state.claimed_groups or gid in state.claiming_groups:
            return
        # P0.3: reserve slot only (don't count total yet — semaphore wait excluded)
        state.claiming_groups.add(gid)

    # P0.3/P2: bound concurrent pipelines to avoid 429 stampede
    async with state.claim_semaphore:
        async with state.claim_state_lock:
            # Re-check after queue: another task may have claimed/ignored meanwhile.
            import time as _t2
            exp2 = state.ignored_groups.get(gid)
            if exp2 and _t2.monotonic() < exp2:
                state.claiming_groups.discard(gid)
                return
            if gid in state.claimed_groups:
                state.claiming_groups.discard(gid)
                return
            state.stats["total"] += 1
        try:
            ok(f"Detected {gid}")
            try:
                from src.claimer import ultimate_claim
                success = await asyncio.wait_for(
                    ultimate_claim(gid), timeout=config.claim_timeout_seconds
                )
            except asyncio.TimeoutError:
                success = False
                warn(f"{gid} - Claim timed out after {config.claim_timeout_seconds:.0f}s")
                asyncio.create_task(send_claim_error_webhook(gid, "Claim timeout"))
            except Exception as e:
                success = False
                fatal(f"{gid} - Claim task error: {type(e).__name__}: {e}")
                asyncio.create_task(
                    send_claim_error_webhook(
                        gid, f"Task exception: {type(e).__name__}: {e}"
                    )
                )

            # P2: single counting point under lock (claimer no longer increments)
            async with state.claim_state_lock:
                if success:
                    state.claimed_groups.add(gid)
                    state.stats["success"] += 1
                else:
                    state.stats["fail"] += 1
            if not success:
                warn(f"Failed {gid}")
        finally:
            async with state.claim_state_lock:
                state.claiming_groups.discard(gid)
            # P1.1: release per-GID lease (best-effort, never fail the claim path)
            try:
                from src.network import release_cookie_for_gid
                await release_cookie_for_gid(gid)
            except Exception:
                pass
