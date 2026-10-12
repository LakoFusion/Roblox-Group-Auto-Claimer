import random
import os
from src.logger import log, warn
import src.config as config

class ProxyManager:
    def __init__(self):
        self.proxies = []
        if config.use_proxies:
            self.load_proxies()

    def load_proxies(self):
        path = config.proxy_file
        if not os.path.exists(path) and os.path.exists("proxies.txt"):
            path = "proxies.txt"
        if not os.path.exists(path):
            warn(f"Proxy file {path} not found. Running without proxies.")
            return

        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split(":")
            if len(parts) == 4:
                host, port, user, pwd = parts
                self.proxies.append(f"http://{user}:{pwd}@{host}:{port}")
            elif len(parts) == 2:
                host, port = parts
                self.proxies.append(f"http://{host}:{port}")
            else:
                self.proxies.append(line if line.startswith("http") else f"http://{line}")

        if self.proxies:
            log(f"Loaded {len(self.proxies)} proxies")
        else:
            warn("No valid proxies found in proxy file.")

    def get_proxy_dict(self):
        if not self.proxies or not config.use_proxies:
            return None
        proxy = random.choice(self.proxies)
        return {"http": proxy, "https": proxy}

    def get_proxy_dict_rotating(self):
        # P1.2: explicit rotating alias — fresh random proxy per call.
        # Returns None when disabled so call sites fall back to session default.
        return self.get_proxy_dict()
