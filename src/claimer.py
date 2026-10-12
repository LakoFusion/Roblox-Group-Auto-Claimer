import time
import asyncio
import src.config as config
import src.state as state
from src.logger import warn, log
from src.network import build_claim_headers, get_roblox_proxies

async def claim_sequential(gid: int, headers: dict, lease: dict | None = None) -> str:
    """Sequential: JOIN → CLAIM."""
    try:
        if lease:
            account_cookie = lease.get("cookie") or state.cookie
            account_xcsrf = lease.get("xcsrf") or state.xcsrf
            account_username = lease.get("username") or state.username
            account_userid = lease.get("userid") or state.userid
        else:
            account_cookie = state.cookie
            account_xcsrf = state.xcsrf
            account_username = state.username
            account_userid = state.userid
        start_total = time.perf_counter()
        loop = asyncio.get_event_loop()

        start_join = time.perf_counter()
        _px1 = get_roblox_proxies()
        jr = await loop.run_in_executor(
            None,
            lambda: state.session.post(
                f"https://groups.roblox.com/v1/groups/{gid}/users", headers=headers,
                proxies=_px1,
            ),
        )
        join_time = (time.perf_counter() - start_join) * 1000

        start_claim = time.perf_counter()
        _px2 = get_roblox_proxies()
        cr = await loop.run_in_executor(
            None,
            lambda: state.session.post(
                f"https://groups.roblox.com/v1/groups/{gid}/claim-ownership",
                headers=headers,
                proxies=_px2,
            ),
        )
        claim_time = (time.perf_counter() - start_claim) * 1000
        total_time = (time.perf_counter() - start_total) * 1000

        if cr.status_code == 200:
            from src.handlers import check_group_value, set_group_status
            asyncio.create_task(
                check_group_value(
                    gid,
                    total_time,
                    join_time,
                    claim_time,
                    0,
                    "Sequential",
                    account_cookie,
                    account_xcsrf,
                    account_username,
                )
            )
            asyncio.create_task(set_group_status(gid, account_cookie, account_xcsrf))
            # P2: success counted once in handle_claim under lock, not here
            return config.CLAIM_SUCCESS

        from src.handlers import handle_claim_errors
        return await handle_claim_errors(
            gid,
            jr,
            cr,
            account_cookie,
            account_xcsrf,
            account_username,
            account_userid,
        )

    except Exception as e:
        warn(f"{gid} - Exception in claim_sequential: {type(e).__name__}: {e}")
        return config.CLAIM_FAILED

async def claim_parallel(gid: int, headers: dict, delay: float, task_id: int, lease: dict | None = None) -> str:
    """Parallel: Fire JOIN then fire CLAIM precisely `delay` seconds later."""
    try:
        if lease:
            account_cookie = lease.get("cookie") or state.cookie
            account_xcsrf = lease.get("xcsrf") or state.xcsrf
            account_username = lease.get("username") or state.username
            account_userid = lease.get("userid") or state.userid
        else:
            account_cookie = state.cookie
            account_xcsrf = state.xcsrf
            account_username = state.username
            account_userid = state.userid
        loop = asyncio.get_event_loop()

        async def do_join():
            start = time.perf_counter()
            _px = get_roblox_proxies()
            r = await loop.run_in_executor(
                None,
                lambda: state.session.post(
                    f"https://groups.roblox.com/v1/groups/{gid}/users", headers=headers,
                    proxies=_px,
                ),
            )
            return r, (time.perf_counter() - start) * 1000

        async def do_claim():
            await asyncio.sleep(delay)
            start = time.perf_counter()
            _px = get_roblox_proxies()
            r = await loop.run_in_executor(
                None,
                lambda: state.session.post(
                    f"https://groups.roblox.com/v1/groups/{gid}/claim-ownership",
                    headers=headers,
                    proxies=_px,
                ),
            )
            return r, (time.perf_counter() - start) * 1000

        start_total = time.perf_counter()
        results = await asyncio.gather(do_join(), do_claim())
        jr, join_time = results[0]
        cr, claim_time = results[1]
        total_time = (time.perf_counter() - start_total) * 1000

        if cr.status_code == 200:
            from src.handlers import check_group_value, set_group_status
            asyncio.create_task(
                check_group_value(
                    gid,
                    total_time,
                    join_time,
                    claim_time,
                    delay,
                    task_id,
                    account_cookie,
                    account_xcsrf,
                    account_username,
                )
            )
            asyncio.create_task(set_group_status(gid, account_cookie, account_xcsrf))
            # P2: success counted once in handle_claim under lock, not here
            return config.CLAIM_SUCCESS

        if jr.status_code == 200 and cr.status_code in (403, 500, 429, 401, 400):
            log(f"{gid} - Parallel #{task_id} JOIN succeeded, doing rapid CLAIM retries")
            for retry_idx, retry_delay in enumerate(config.post_join_retry_delays):
                await asyncio.sleep(retry_delay)
                start_retry = time.perf_counter()
                _pxr = get_roblox_proxies()
                cr_retry = await loop.run_in_executor(
                    None,
                    lambda: state.session.post(
                        f"https://groups.roblox.com/v1/groups/{gid}/claim-ownership",
                        headers=headers,
                        proxies=_pxr,
                    ),
                )
                retry_claim_time = (time.perf_counter() - start_retry) * 1000
                total_time = (time.perf_counter() - start_total) * 1000

                if cr_retry.status_code == 200:
                    from src.handlers import check_group_value, set_group_status
                    asyncio.create_task(
                        check_group_value(
                            gid,
                            total_time,
                            join_time,
                            retry_claim_time,
                            delay + retry_delay,
                            f"{task_id} (Retry {retry_idx + 1})",
                            account_cookie,
                            account_xcsrf,
                            account_username,
                        )
                    )
                    asyncio.create_task(
                        set_group_status(gid, account_cookie, account_xcsrf)
                    )
                    # P2: success counted once in handle_claim under lock, not here
                    return config.CLAIM_SUCCESS

                if cr_retry.status_code not in (403, 500, 429):
                    cr = cr_retry
                    break

        from src.handlers import handle_claim_errors
        return await handle_claim_errors(
            gid,
            jr,
            cr,
            account_cookie,
            account_xcsrf,
            account_username,
            account_userid,
        )

    except Exception as e:
        warn(f"{gid} - Exception in claim_parallel #{task_id}: {type(e).__name__}: {e}")
        return config.CLAIM_FAILED

async def ultimate_claim(gid: int) -> bool:
    # P1.1: per-GID lease — no global thrash. Falls back to global state if lease fails.
    from src.network import (
        acquire_cookie_for_gid,
        ensure_fresh_lease_xcsrf,
        refresh_lease_xcsrf,
    )
    lease = await acquire_cookie_for_gid(gid)
    if not lease:
        if not state.cookie:
            return False
        lease = {
            "cookie": state.cookie,
            "xcsrf": state.xcsrf,
            "username": state.username,
            "userid": state.userid,
            "ts": time.time(),
        }
    for attempt in range(config.claim_retry_attempts):
        await ensure_fresh_lease_xcsrf(lease)
        # Sync lease token from store (another task may have refreshed same cookie)
        try:
            async with state.cookie_switch_lock:
                stored = state.cookie_leases.get(gid)
                if stored and stored.get("cookie") == lease.get("cookie") and stored.get("xcsrf"):
                    lease["xcsrf"] = stored["xcsrf"]
                    lease["ts"] = stored.get("ts", lease.get("ts", time.time()))
        except Exception:
            pass
        attempt_cookie = lease.get("cookie")
        attempt_xcsrf = lease.get("xcsrf")
        if not attempt_cookie:
            return False
        headers = build_claim_headers(attempt_cookie, attempt_xcsrf)
        result = config.CLAIM_FAILED

        if config.claim_mode == "sequential":
            result = await claim_sequential(gid, headers, lease)
        else:
            tasks = [
                claim_parallel(gid, headers, delay, i + 1, lease)
                for i, delay in enumerate(config.parallel_delays)
            ]
            results = await asyncio.gather(*tasks)

            if config.CLAIM_SUCCESS in results:
                return True

            for r in [config.CLAIM_RETRY_COOKIE, config.CLAIM_RETRY_XCSRF, config.CLAIM_FAILED]:
                if r in results:
                    result = r
                    break

        if result == config.CLAIM_SUCCESS:
            return True

        if result == config.CLAIM_RETRY_XCSRF:
            before = attempt_xcsrf
            await refresh_lease_xcsrf(gid)
            try:
                async with state.cookie_switch_lock:
                    stored = state.cookie_leases.get(gid)
                    if stored and stored.get("cookie") == attempt_cookie and stored.get("xcsrf"):
                        lease["xcsrf"] = stored["xcsrf"]
                        lease["ts"] = stored.get("ts", time.time())
            except Exception:
                pass
            if lease.get("xcsrf") != before:
                warn(f"{gid} - Retrying with refreshed XCSRF ({attempt + 1}/{config.claim_retry_attempts})")
                continue
            return False

        if result == config.CLAIM_RETRY_COOKIE:
            # P0.3: don't spam webhook per attempt — handle_claim_errors already
            # sent AccountFull when "maximum", final failure is reported below.
            # P1.1: mark THIS lease cookie full (under lock), then lease a new one.
            try:
                async with state.cookie_switch_lock:
                    if state.cookie_mgr:
                        state.cookie_mgr.mark_full(attempt_cookie)
                    state.cookie_leases.pop(gid, None)
            except Exception:
                pass
            new_lease = await acquire_cookie_for_gid(gid)
            if new_lease:
                lease = new_lease
                warn(f"{gid} - Retrying with next account ({attempt + 1}/{config.claim_retry_attempts})")
                continue
            return False

        return False

    warn(f"{gid} - Retry limit reached")
    from src.webhooks import send_claim_error_webhook
    asyncio.create_task(send_claim_error_webhook(gid, "Retry limit reached"))
    return False
