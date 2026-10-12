import json

# Constants
CLAIM_SUCCESS = "success"
CLAIM_FAILED = "failed"
CLAIM_RETRY_COOKIE = "retry_cookie"
CLAIM_RETRY_XCSRF = "retry_xcsrf"

APP_NAME = "Ultra Fusion"
EMBED_NAME = "⚡ Ultra Fusion"
# Embed V2 modern palette (Discord-native hex)
COLOR_INFO = 0x5865F2      # Blurple — system / online
COLOR_SUCCESS = 0x57F287   # Emerald — normal claim
COLOR_WARN = 0xE67E22      # Sunset orange — warning / full
COLOR_ERROR = 0xED4245     # Crimson — failed
COLOR_GOLD = 0xFEE75C      # Electric gold — high value

# Config variables
webhooks = {}
token = ""
prefix = "--"
owner_ids = set()
claim_mode = "parallel"
parallel_delays = [0.05, 0.10, 0.15]
post_join_retry_delays = [0.35, 0.80, 1.60, 2.50]
claim_retry_attempts = 3
claim_timeout_seconds = 12.0
verbose_logs = False
dashboard = True
dashboard_always_log = False
use_proxies = False
proxy_file = "input/proxies.txt"
cookie_file = "input/cookies.txt"

def load_config():
    global webhooks, token, prefix, claim_mode, parallel_delays
    global post_join_retry_delays, claim_retry_attempts, claim_timeout_seconds, verbose_logs
    global use_proxies, proxy_file, owner_ids, cookie_file, dashboard, dashboard_always_log

    with open("config.json", "r") as f:
        config_data = json.load(f)
        webhooks = config_data["webhooks"]
        token = config_data["token"]
        prefix = config_data.get("prefix", "--")
        # P0.1 (config-only): Discord IDs allowed to run commands (NOT Roblox user id).
        # Supports: ["id1","id2"], "id1,id2", 12345, single "owner_id" key.
        raw_owners = config_data.get("owner_ids", [])
        if isinstance(raw_owners, (str, int)):
            raw_owners = [raw_owners]
        owner_ids = set()
        for x in (raw_owners or []):
            for part in str(x).split(","):
                part = part.strip()
                if part:
                    owner_ids.add(part)
        # Back-compat single key
        single = config_data.get("owner_id", "")
        if single and str(single).strip():
            owner_ids.add(str(single).strip())

        # Claim strategy config
        claim_mode = str(config_data.get("claim_mode", "parallel")).lower()
        parallel_delays = [
            float(d) for d in config_data.get("parallel_delays", [0.05, 0.10, 0.15])
        ]
        post_join_retry_delays = [
            float(d) for d in config_data.get("post_join_retry_delays", [0.35, 0.80, 1.60, 2.50])
        ]
        claim_retry_attempts = max(1, int(config_data.get("claim_retry_attempts", 3)))
        claim_timeout_seconds = max(3.0, float(config_data.get("claim_timeout_seconds", 12)))
        verbose_logs = bool(config_data.get("verbose_logs", False))
        dashboard = bool(config_data.get("dashboard", True))
        dashboard_always_log = bool(config_data.get("dashboard_always_log", False))
        use_proxies = bool(config_data.get("use_proxies", False))
        proxy_file = str(config_data.get("proxy_file", "input/proxies.txt"))
        cookie_file = str(config_data.get("cookie_file", "input/cookies.txt"))

load_config()
