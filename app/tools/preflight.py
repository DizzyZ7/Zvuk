"""Run inside the app container to inspect connectivity without printing secrets.

Usage: docker compose run --rm --no-deps bot python -m app.tools.preflight
"""
import os
import shutil
import socket
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def public_ip(url: str = "https://api.ipify.org") -> str | None:
    try:
        with urlopen(Request(url, headers={"User-Agent": "Zvuk-preflight/1.0"}), timeout=8) as r:
            ip = r.read(80).decode("ascii").strip()
            socket.inet_pton(socket.AF_INET6 if ":" in ip else socket.AF_INET, ip)
            return ip
    except (OSError, UnicodeError, ValueError, URLError, HTTPError):
        return None


def https_reachable(url: str) -> bool:
    try:
        with urlopen(Request(url, method="HEAD"), timeout=8):
            return True
    except HTTPError as exc:
        # 401/403/404 still prove that HTTPS traffic reached the destination.
        return 400 <= exc.code < 500
    except (OSError, URLError, ValueError):
        return False


def tcp_reachable(url: str, *, fallback_port: int) -> bool:
    try:
        value = urlsplit(url)
        if not value.hostname:
            return False
        with socket.create_connection(
            (value.hostname, value.port or fallback_port), timeout=3,
        ):
            return True
    except (OSError, ValueError):
        return False


def environment_issues(env: dict[str, str]) -> list[str]:
    problems = []
    for name in ("BOT_TOKEN", "TELEGRAM_API_HASH", "POSTGRES_PASSWORD"):
        value = env.get(name, "").strip()
        if not value or "replace" in value.lower() or "choose_" in value.lower():
            problems.append(f"Не заполнено {name}")
    try:
        if int(env.get("TELEGRAM_API_ID", "0")) <= 0:
            problems.append("Некорректный TELEGRAM_API_ID")
    except ValueError:
        problems.append("Некорректный TELEGRAM_API_ID")
    if env.get("PREMIUM_ENABLED", "false").lower() in {"true", "1", "yes"}:
        problems.append("Premium включен: для первых тестов используйте PREMIUM_ENABLED=false")
    return problems


def main() -> int:
    print("🧪 Zvuk preflight: ни токены, ни пароли не выводятся")
    problems = environment_issues(dict(os.environ))
    for problem in problems:
        print(f"[!] {problem}")

    for executable in ("ffmpeg", "node"):
        print(f"[{'OK' if shutil.which(executable) else 'FAIL'}] {executable}")

    services = [
        ("PostgreSQL", os.getenv("DATABASE_URL", ""), 5432),
        ("Redis", os.getenv("REDIS_URL", ""), 6379),
        ("Local Bot API", os.getenv("BOT_API_URL", ""), 8081),
    ]
    for label, url, port in services:
        result = tcp_reachable(url, fallback_port=port)
        print(f"[{'OK' if result else 'FAIL'}] TCP {label}")

    for label, url in (
        ("Telegram cloud HTTPS", "https://api.telegram.org"),
        ("YouTube HTTPS", "https://www.youtube.com"),
    ):
        result = https_reachable(url)
        print(f"[{'OK' if result else 'FAIL'}] {label}")

    ip = public_ip()
    print(f"🌐 Внешний IP контейнера: {ip or 'не удалось определить'}")
    print(
        "Сравните его с IP Windows при включенном VPN: "
        "Invoke-RestMethod https://api.ipify.org"
    )
    print(
        "При разных IP нельзя считать, что весь трафик Docker идет через VPN. "
        "Перезапустите Docker Desktop после подключения VPN и повторите проверку."
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
