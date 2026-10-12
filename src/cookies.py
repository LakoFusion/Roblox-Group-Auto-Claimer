import os
from src.logger import log, warn
import src.config as config

class CookieManager:
    def __init__(self):
        path = getattr(config, "cookie_file", "input/cookies.txt")
        if not os.path.exists(path) and os.path.exists("cookies.txt"):
            path = "cookies.txt"
        if not os.path.exists(path):
            warn(f"Cookie file {path} not found. No cookies loaded.")
            self.cookies = []
        else:
            with open(path, "r") as f:
                self.cookies = [c.strip() for c in f.readlines() if c.strip()]
        self.index = 0
        self.full_cookies = set()
        log(f"Loaded {len(self.cookies)} cookies from {path}")

    def get_next(self):
        """Get next available cookie sequentially, skipping full ones"""
        if not self.cookies:
            return None
        tried = 0
        while tried < len(self.cookies):
            c = self.cookies[self.index]
            self.index = (self.index + 1) % len(self.cookies)
            if c not in self.full_cookies:
                return c
            tried += 1
        return None

    def mark_full(self, cookie: str):
        self.full_cookies.add(cookie)

    def available_count(self):
        return len(self.cookies) - len(self.full_cookies)

    def is_exhausted(self):
        return self.available_count() == 0
