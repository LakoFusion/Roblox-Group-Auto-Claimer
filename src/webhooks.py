import asyncio
from datetime import datetime, timezone
from typing import Optional
import src.config as config
import src.state as state
from src.logger import footer_text, log

def _ds():
    return getattr(state, "discord_session", None) or state.session

async def send_claim_error_webhook(gid: int, reason: str, join_status: int = 0, claim_status: int = 0):
    """Send webhook for claim errors."""
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: _ds().post(
                config.webhooks["errors"],
                json={
                    "username": config.EMBED_NAME,
                    "embeds": [
                        {
                            "author": {"name": f"{config.APP_NAME} • FAILED"},
                            "title": f"❌ Group {gid}",
                            "description": (
                                f"⚠️ Reason: **{reason}**\n"
                                f"📡 Network: JOIN {join_status} | CLAIM {claim_status}\n"
                                f"👤 Account: **{state.username}** (auto-left)"
                            ),
                            "url": f"https://roblox.com/groups/{gid}",
                            "color": config.COLOR_ERROR,
                            "footer": {"text": footer_text()},
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ],
                },
            ),
        )
    except Exception as e:
        log(f"Webhook claim-error failed: {type(e).__name__}")

async def send_account_full_webhook(uname: str, uid: Optional[int], remaining: int, total: int):
    """Send webhook when account is full"""
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: _ds().post(
                config.webhooks["errors"],
                json={
                    "username": config.EMBED_NAME,
                    "embeds": [
                        {
                            "author": {"name": f"{config.APP_NAME} • ALERT"},
                            "title": f"⚠️ Full: {uname}",
                            "description": (
                                f"📦 Status: Reached max group limit\n"
                                f"🍪 Available Pool: **{remaining}/{total}** cookies remaining\n"
                                f"🔄 Action: Switching to next account"
                            ),
                            "color": config.COLOR_WARN if remaining > 0 else config.COLOR_ERROR,
                            "footer": {"text": footer_text()},
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ],
                },
            ),
        )
    except Exception as e:
        log(f"Webhook account-full failed: {type(e).__name__}")

async def send_all_cookies_exhausted_webhook():
    """Send webhook when all cookies are exhausted"""
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: _ds().post(
                config.webhooks["errors"],
                json={
                    "username": config.EMBED_NAME,
                    "embeds": [
                        {
                            "author": {"name": f"{config.APP_NAME} • HALTED"},
                            "title": "🚨 Cookies Exhausted",
                            "description": (
                                f"📦 Status: **{len(state.cookie_mgr.full_cookies)}/{len(state.cookie_mgr.cookies)}** cookies full\n"
                                f"🔄 Action: Add fresh cookies and restart"
                            ),
                            "color": config.COLOR_ERROR,
                            "footer": {"text": footer_text()},
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ],
                },
            ),
        )
    except Exception as e:
        log(f"Webhook exhausted failed: {type(e).__name__}")
