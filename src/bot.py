import json
import asyncio
import os
import random
import websockets
import re
from datetime import datetime, timezone

import src.config as config
import src.state as state
from src.logger import log, warn, fatal, ok, render_dashboard, account_label, delays_label, footer_text
from src.network import switch_cookie
from src.handlers import handle_claim
from src.cookies import CookieManager

class Discord:
    def __init__(self, t):
        self.token = t
        self.ws = None
        self.hb_task = None
        self.seq = None
        self.sid = None
        self.url = None
        self.connected = False
        self.last_hb_ack = True

    async def connect(self):
        while True:
            try:
                uri = self.url or "wss://gateway.discord.gg/?v=10&encoding=json"
                async with websockets.connect(
                    uri, max_size=2**25, ping_interval=None
                ) as ws:
                    self.ws = ws
                    self.connected = True
                    self.last_hb_ack = True

                    if self.sid and self.seq:
                        log(f"Resuming session (seq={self.seq})")
                        await self.ws.send(
                            json.dumps(
                                {
                                    "op": 6,
                                    "d": {
                                        "token": self.token,
                                        "session_id": self.sid,
                                        "seq": self.seq,
                                    },
                                }
                            )
                        )
                    else:
                        await self.ws.send(
                            json.dumps(
                                {
                                    "op": 2,
                                    "d": {
                                        "token": self.token,
                                        "properties": {
                                            "$os": "windows",
                                            "$browser": "chrome",
                                            "$device": "chrome",
                                        },
                                        "intents": 33281,
                                    },
                                }
                            )
                        )

                    await self.listen()
            except Exception as e:
                self.connected = False
                if self.hb_task:
                    self.hb_task.cancel()
                    try:
                        await self.hb_task
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass
                    self.hb_task = None
                warn(
                    f"Gateway disconnected: {type(e).__name__}: {e} | Reconnecting in 3s..."
                )
                await asyncio.sleep(3)

    async def listen(self):
        ws = self.ws
        if ws is None:
            return

        async for msg in ws:
            try:
                e = json.loads(msg)
                op = e.get("op")

                if e.get("s"):
                    self.seq = e["s"]

                if op == 10:
                    hb = e["d"]["heartbeat_interval"]
                    self.url = e["d"].get("resume_gateway_url")
                    if self.hb_task:
                        self.hb_task.cancel()
                        try:
                            await self.hb_task
                        except asyncio.CancelledError:
                            pass
                        except Exception:
                            pass
                    self.hb_task = asyncio.create_task(self.heartbeat(hb))

                elif op == 11:
                    self.last_hb_ack = True

                elif op == 7:
                    warn("Gateway requested reconnect (op 7)")
                    await ws.close()
                    return

                elif op == 9:
                    resumable = e.get("d", False)
                    warn(f"Invalid session (op 9) | resumable={resumable}")
                    if not resumable:
                        self.sid = None
                        self.seq = None
                    await asyncio.sleep(random.uniform(1, 5))
                    await ws.close()
                    return

                elif op == 0:
                    t = e["t"]

                    if t == "READY":
                        self.sid = e["d"]["session_id"]
                        self.url = e["d"]["resume_gateway_url"]
                        try:
                            state.discord_self_id = str(e["d"]["user"]["id"])
                        except Exception:
                            pass
                        os.system("cls" if os.name == "nt" else "clear")
                        render_dashboard(e["d"]["user"]["username"])
                        ok(f"Monitoring {len(e['d']['guilds'])} guilds")

                    elif t == "RESUMED":
                        ok(f"Session resumed successfully (seq={self.seq})")

                    elif t == "MESSAGE_CREATE":
                        asyncio.create_task(self.handle_msg(e["d"]))

            except Exception as e:
                fatal(f"Error processing gateway event: {type(e).__name__}: {e}")

    async def handle_msg(self, d):
        c = d.get("content", "") or ""

        if c.startswith(config.prefix):
            # P0.1 (config-only): Discord author must be in owner_ids (multi-ID),
            # else only the logged-in account. Pre-READY (self id unknown) denies.
            a = str(d.get("author", {}).get("id"))
            if config.owner_ids:
                allowed = a in config.owner_ids
            else:
                allowed = state.discord_self_id is not None and a == str(state.discord_self_id)
            if allowed:
                ch = d.get("channel_id")
                if c == f"{config.prefix}stats":
                    await self.send_embed(
                        ch,
                        {
                            "author": {"name": f"{config.APP_NAME} • LIVE STATS"},
                            "title": "📊 Real-time Statistics",
                            "description": (
                                f"👁️ Total Seen: **{state.stats['total']} groups**\n"
                                f"✅ Claimed: **{state.stats['success']} groups**\n"
                                f"❌ Failed: **{state.stats['fail']} groups**\n"
                                f"🍪 Cookies: **{state.cookie_mgr.available_count()}/{len(state.cookie_mgr.cookies)} ready**\n"
                                f"👤 Active: **{state.username}**"
                            ),
                            "color": config.COLOR_INFO,
                            "footer": {"text": footer_text()},
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                elif c == f"{config.prefix}switch":
                    await switch_cookie()
                    await self.send_embed(
                        ch,
                        {
                            "author": {"name": f"{config.APP_NAME} • SESSION"},
                            "title": "🔄 Account Switched",
                            "description": (
                                f"👤 New Account: **{state.username}**\n"
                                f"🆔 User ID: **{state.userid}**"
                            ),
                            "color": config.COLOR_SUCCESS,
                            "footer": {"text": footer_text()},
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    )
            return

        texts = [c]
        for embed in d.get("embeds", []):
            for key in ("title", "description", "url"):
                if embed.get(key):
                    texts.append(embed[key])
            for field in embed.get("fields", []):
                if field.get("name"):
                    texts.append(field["name"])
                if field.get("value"):
                    texts.append(field["value"])
            if embed.get("author", {}).get("url"):
                texts.append(embed["author"]["url"])

        combined = " ".join(texts)
        # P1.3: keep 2 legacy patterns, add rblx.gg / share links (additive only).
        group_ids = {
            int(m.group(1))
            for m in re.finditer(r"(?:groups|communities)/(\d+)", combined, re.I)
        }
        group_ids.update(
            int(m.group(1))
            for m in re.finditer(r"groups\.aspx\?gid=(\d+)", combined, re.I)
        )
        group_ids.update(
            int(m.group(1))
            for m in re.finditer(r"rblx\.gg/group[s]?/(\d+)", combined, re.I)
        )
        group_ids.update(
            int(m.group(1))
            for m in re.finditer(r"roblox\.com/share\?[^ ]*?code=\w+[-_]*gid=(\d+)", combined, re.I)
        )
        group_ids.update(
            int(m.group(1))
            for m in re.finditer(r"roblox\.com/(?:groups|communities)/(\d+)", combined, re.I)
        )

        # P1.3: bound fan-out — drop (with log) instead of spawning unbounded tasks.
        for gid in group_ids:
            try:
                if state.inbound_semaphore.locked():
                    warn(f"Inbound burst dropped {gid} (too many pending)")
                    continue
            except Exception:
                pass
            asyncio.create_task(self._handle_claim_release(gid))

    async def _handle_claim_release(self, gid: int):
        async with state.inbound_semaphore:
            await handle_claim(gid)

    async def send_embed(self, ch, embed: dict):
        try:
            loop = asyncio.get_event_loop()
            sess = getattr(state, "discord_session", None) or state.session
            await loop.run_in_executor(
                None,
                lambda: sess.post(
                    f"https://discord.com/api/v9/channels/{ch}/messages",
                    json={"username": config.EMBED_NAME, "embeds": [embed]},
                    headers={"authorization": self.token},
                ),
            )
        except Exception as e:
            if config.verbose_logs:
                warn(f"Discord send failed: {type(e).__name__}")

    async def heartbeat(self, i):
        while self.connected:
            await asyncio.sleep(i / 1000)
            try:
                if not self.last_hb_ack:
                    warn(
                        "No heartbeat ACK received — zombie connection, forcing reconnect"
                    )
                    self.connected = False
                    if self.ws:
                        await self.ws.close()
                    return
                self.last_hb_ack = False
                if self.ws and self.connected:
                    await self.ws.send(json.dumps({"op": 1, "d": self.seq}))
            except:
                warn("Heartbeat send failed, forcing reconnect")
                self.connected = False
                if self.ws:
                    try:
                        await self.ws.close()
                    except:
                        pass
                return

async def run_bot():
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except Exception:
        pass

    os.system("cls" if os.name == "nt" else "clear")

    from src.network import init_session, xcsrf_refresher
    from src.logger import print_status
    state.cookie_mgr = CookieManager()
    init_session()
    await switch_cookie()

    if not state.cookie:
        fatal("No valid cookies!")
        return

    asyncio.create_task(xcsrf_refresher())
    log("XCSRF auto-refresh started")

    async def dashboard_renderer():
        while True:
            try:
                if getattr(config, "dashboard", True):
                    print_status()
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception:
                try:
                    await asyncio.sleep(1.0)
                except asyncio.CancelledError:
                    break

    asyncio.create_task(dashboard_renderer())

    try:
        loop = asyncio.get_event_loop()
        sess = getattr(state, "discord_session", None) or state.session
        await loop.run_in_executor(
            None,
            lambda: sess.post(
                config.webhooks["logs"],
                json={
                    "username": config.EMBED_NAME,
                    "embeds": [
                        {
                            "author": {"name": f"{config.APP_NAME}"},
                            "title": "🚀 Ready for instant claim",
                            "description": (
                                f"⚙️ Mode: **{config.claim_mode.upper()} ({delays_label()})**\n"
                                f"👤 Active Account: **{account_label()}**\n"
                                f"🍪 Pool: **{state.cookie_mgr.available_count()}/{len(state.cookie_mgr.cookies)} cookies ready**"
                            ),
                            "color": config.COLOR_INFO,
                            "footer": {"text": "Chrome impersonation • Auto XCSRF"},
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ],
                },
            ),
        )
    except:
        pass

    client = Discord(config.token)
    await client.connect()
