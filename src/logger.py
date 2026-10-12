from datetime import datetime
import sys
from colorama import Fore, Style
import src.config as config
import src.state as state

RECENT_MAX = 10


def _push_recent(text: str):
    try:
        logs = getattr(state, "recent_logs", None)
        if logs is None:
            state.recent_logs = logs = []
        logs.append(text)
        while len(logs) > RECENT_MAX:
            logs.pop(0)
    except Exception:
        pass

def timet():
    return (
        Style.DIM
        + Fore.BLACK
        + f"[{datetime.now().strftime('%I:%M:%S')}]"
        + Style.RESET_ALL
    )

def emit(level: str, icon: str, color: str, text: str):
    try:
        _push_recent(f"[{datetime.now().strftime('%H:%M:%S')}] {icon} {text}")
    except Exception:
        pass
    # Dashboard-live mode: renderer owns the screen, skip direct print (anti-flicker).
    try:
        if getattr(state, "dashboard_live", False) and not getattr(config, "dashboard_always_log", False):
            return
    except Exception:
        pass
    print(
        f"{timet()} {Style.BRIGHT}{color}{icon} {level:<7}{Style.RESET_ALL} {Fore.WHITE}{text}{Fore.RESET}"
    )

def log(text):
    if config.verbose_logs:
        emit("INFO", "•", Fore.LIGHTMAGENTA_EX, text)

def ok(text):
    emit("OK", "✓", Fore.LIGHTGREEN_EX, text)

def warn(text):
    emit("WARN", "!", Fore.LIGHTYELLOW_EX, text)

def fatal(text):
    emit("ERROR", "×", Fore.LIGHTRED_EX, text)

def fmt_num(value) -> str:
    return f"{int(value):,}"

def fmt_ms(value: float) -> str:
    return f"{value:.0f}ms"

def delays_label() -> str:
    if config.claim_mode == "sequential":
        return "JOIN → CLAIM"
    return " / ".join(f"{int(delay * 1000)}ms" for delay in config.parallel_delays)

def account_label(name=None, uid=None) -> str:
    name = name or state.username or "Unknown"
    uid = uid or state.userid or "?"
    return f"{name} ({uid})"

def footer_text() -> str:
    try:
        if state.cookie_mgr:
            return f"{config.claim_mode.upper()} • {state.cookie_mgr.available_count()}/{len(state.cookie_mgr.cookies)} cookies"
        return config.claim_mode.upper()
    except Exception:
        return config.claim_mode.upper()

def render_dashboard(discord_user: str):
    # Legacy header kept for compat; enables live dashboard renderer afterwards.
    try:
        state.dashboard_live = True
    except Exception:
        pass
    available = state.cookie_mgr.available_count() if state.cookie_mgr else 0
    total = len(state.cookie_mgr.cookies) if state.cookie_mgr else 0
    print(
        f"{Style.BRIGHT}{Fore.RED}⚡ {config.APP_NAME}{Fore.RESET} {Fore.LIGHTBLACK_EX}online{Fore.RESET}"
    )
    print(
        f"{Fore.WHITE}Discord {Fore.LIGHTBLACK_EX}{discord_user}{Fore.RESET} • "
        f"{Fore.WHITE}Roblox {Fore.LIGHTBLACK_EX}{state.username} ({state.userid}){Fore.RESET}"
    )
    print(
        f"{Fore.WHITE}Mode {Fore.LIGHTBLACK_EX}{config.claim_mode.upper()} • {delays_label()}{Fore.RESET} • "
        f"{Fore.WHITE}Cookies {Fore.LIGHTBLACK_EX}{available}/{total}{Fore.RESET} • "
        f"{Fore.WHITE}Retry {Fore.LIGHTBLACK_EX}{config.claim_retry_attempts}x/{config.claim_timeout_seconds:.0f}s{Fore.RESET}\n"
    )


def print_status(s=None):
    """Ultra-compact minimalist console renderer.

    Shows only what a group claimer needs: account, cookies (+proxies if on),
    stats (seen/claimed/failed + in-flight gid), and 4 recent logs.
    No box chars, whitespace alignment only, single-buffered anti-flicker flush.
    """
    try:
        BOLD_WHITE = "\033[1;97m"
        CYAN = "\033[1;96m"
        GREEN = "\033[1;92m"
        YELLOW = "\033[1;93m"
        RED = "\033[1;91m"
        DIM = "\033[90m"
        RST = "\033[0m"

        if s is None:
            import types
            try:
                claiming = sorted(getattr(state, "claiming_groups", set()))
            except Exception:
                claiming = []
            try:
                stats = getattr(state, "stats", {}) or {}
                n_seen = int(stats.get("total", 0))
                n_ok = int(stats.get("success", 0))
                n_fail = int(stats.get("fail", 0))
            except Exception:
                n_seen, n_ok, n_fail = 0, 0, 0
            try:
                mode = str(getattr(config, "claim_mode", "parallel")).lower()
                delays = list(getattr(config, "parallel_delays", [0.05, 0.10, 0.15]))
            except Exception:
                mode, delays = "parallel", [0.05, 0.10, 0.15]
            if mode == "sequential":
                mode_txt = "SEQUENTIAL"
            else:
                mode_txt = "PARALLEL • " + "/".join(f"{int(float(d) * 1000)}ms" for d in delays[:3])
            try:
                mgr = getattr(state, "cookie_mgr", None)
                ck_ok = int(mgr.available_count()) if mgr else 0
                ck_all = int(len(mgr.cookies)) if mgr else 0
            except Exception:
                ck_ok, ck_all = 0, 0
            try:
                pmgr = getattr(state, "proxy_mgr", None)
                px_list = list(getattr(pmgr, "proxies", []) or [])
            except Exception:
                px_list = []
            s = types.SimpleNamespace(
                app_name=getattr(config, "APP_NAME", "ULTRA FUSION"),
                version="v2.4",
                mode=mode_txt,
                account=getattr(state, "username", "") or "Unknown",
                account_id=str(getattr(state, "userid", "") or "?"),
                seen=n_seen,
                claimed=n_ok,
                failed=n_fail,
                claiming=claiming,
                ck_ok=ck_ok,
                ck_all=ck_all,
                use_proxies=bool(getattr(config, "use_proxies", False)),
                px_ok=len(px_list) if getattr(config, "use_proxies", False) else 0,
                px_all=len(px_list) if getattr(config, "use_proxies", False) else 0,
                recent_activity=list(getattr(state, "recent_logs", []) or []),
            )

        app_name = str(getattr(s, "app_name", "ULTRA FUSION")).strip().upper()
        version = str(getattr(s, "version", "v2.4")).strip()
        mode_txt = str(getattr(s, "mode", "PARALLEL")).strip().upper()
        account = str(getattr(s, "account", "Unknown")).strip()
        account_id = str(getattr(s, "account_id", "?")).strip()
        try:
            n_seen = int(getattr(s, "seen", 0) or 0)
            n_ok = int(getattr(s, "claimed", getattr(s, "bought", 0)) or 0)
            n_fail = int(getattr(s, "failed", 0) or 0)
        except Exception:
            n_seen, n_ok, n_fail = 0, 0, 0
        raw_claiming = getattr(s, "claiming", getattr(s, "queue", []))
        if isinstance(raw_claiming, (set, frozenset)):
            claiming = sorted(raw_claiming)
        elif isinstance(raw_claiming, (list, tuple)):
            claiming = list(raw_claiming)
        else:
            claiming = []
        try:
            ck_ok = int(getattr(s, "ck_ok", 0))
            ck_all = int(getattr(s, "ck_all", 0))
        except Exception:
            ck_ok, ck_all = 0, 0
        use_px = bool(getattr(s, "use_proxies", False))
        try:
            px_ok = int(getattr(s, "px_ok", getattr(s, "proxy_alive", 0)) or 0)
            px_all = int(getattr(s, "px_all", getattr(s, "proxy_total", 0)) or 0)
        except Exception:
            px_ok, px_all = 0, 0
        activities = getattr(s, "recent_activity", [])
        if not isinstance(activities, (list, tuple)):
            activities = []

        lines = []
        header_l = f"{BOLD_WHITE}{app_name}{RST} {DIM}{version}{RST}"
        header_r = f"{DIM}{mode_txt}{RST}"
        lines.append(f"{header_l:<32} {header_r:>42}")
        lines.append("")
        lines.append(f"{CYAN}{'ACCOUNT':<10}{RST} {BOLD_WHITE}{account}{RST} {DIM}({account_id}){RST}")
        lines.append(f"{CYAN}{'COOKIES':<10}{RST} {BOLD_WHITE}{ck_ok} / {ck_all}{RST} {DIM}ready{RST}")
        if use_px:
            px_color = GREEN if px_ok > 0 else RED
            lines.append(f"{CYAN}{'PROXIES':<10}{RST} {px_color}{px_ok} / {px_all}{RST} {DIM}active{RST}")
        stats_line = (
            f"{CYAN}{'STATS':<10}{RST} {DIM}Seen{RST} {BOLD_WHITE}{n_seen}{RST}  "
            f"{DIM}• Claimed{RST} {GREEN}{n_ok}{RST}  "
            f"{DIM}• Failed{RST} {RED if n_fail else DIM}{n_fail}{RST}"
        )
        if claiming:
            stats_line += f"            {YELLOW}CLAIMING {claiming[0]}{RST}"
        lines.append(stats_line)
        lines.append("")
        lines.append(f"{CYAN}RECENT ACTIVITY{RST}")
        recent_slice = list(activities[-4:]) if activities else []
        if not recent_slice:
            lines.append(f"  {DIM}Waiting for Discord feed...{RST}")
        else:
            for item in recent_slice:
                text = str(item).strip()
                if "Claimed" in text or text.startswith(">"):
                    tag_color, tag = GREEN, ">"
                elif text.startswith("!") or "error" in text.lower() or "fail" in text.lower() or "owner" in text.lower():
                    tag_color, tag = RED, "!"
                else:
                    tag_color, tag = DIM, "-"
                clean_text = text.lstrip(">-! ").strip()
                if len(clean_text) > 80:
                    clean_text = clean_text[:77] + "..."
                lines.append(f"  {tag_color}{tag}{RST} {clean_text}")

        for _ in range(max(0, 4 - len(recent_slice) if recent_slice else 3)):
            lines.append("")

        lines.append(f"{DIM}[Ctrl+C to stop]{RST}")

        sys.stdout.write("\033[H\033[J" + "\n".join(lines) + "\n")
        sys.stdout.flush()
    except Exception:
        pass
