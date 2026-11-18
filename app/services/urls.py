import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

LINK_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
HOSTS = {
    "youtube.com": "youtube", "www.youtube.com": "youtube",
    "m.youtube.com": "youtube", "youtu.be": "youtube",
    "music.youtube.com": "youtube",
    "vk.com": "vk", "m.vk.com": "vk", "vkvideo.ru": "vk",
    "music.yandex.ru": "yandex", "music.yandex.com": "yandex",
    "rutube.ru": "rutube", "www.rutube.ru": "rutube",
    "tiktok.com": "tiktok", "www.tiktok.com": "tiktok",
    "vm.tiktok.com": "tiktok", "vt.tiktok.com": "tiktok",
    "open.spotify.com": "spotify",
}

class InvalidMediaURL(ValueError):
    pass

@dataclass(frozen=True)
class MediaURL:
    url: str
    platform: str
    default_kind: str | None

def parse_media_url(raw: str) -> MediaURL:
    if len(raw) > 2048:
        raise InvalidMediaURL("Слишком длинная ссылка.")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise InvalidMediaURL("Некорректная ссылка.") from exc
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise InvalidMediaURL("Нужна ссылка http(s) на поддерживаемый сервис.")
    if parsed.username or parsed.password or port is not None:
        raise InvalidMediaURL("Некорректная ссылка.")
    host = parsed.hostname.lower().rstrip(".")
    platform = HOSTS.get(host)
    if platform is None:
        raise InvalidMediaURL("Этот сервис пока не поддерживается.")
    if platform == "spotify":
        if not re.fullmatch(r"/track/[A-Za-z0-9]{22}/?", parsed.path):
            raise InvalidMediaURL("Spotify: поддерживаются только ссылки на отдельные треки.")
        url = f"https://open.spotify.com{parsed.path.rstrip('/')}"
    elif platform == "youtube":
        video_id = ""
        if host == "youtu.be":
            video_id = parsed.path.strip("/").split("/")[0]
        elif parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
            video_id = parsed.path.split("/")[2]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            url = f"https://www.youtube.com/watch?v={video_id}"
        else:
            url = urlunsplit(("https", host, parsed.path, parsed.query, ""))
    else:
        query = [(k, v) for k, values in parse_qs(parsed.query).items()
                 for v in values if k.lower() not in {"utm_source", "utm_medium", "utm_campaign", "fbclid", "si"}]
        url = urlunsplit(("https", host, parsed.path, urlencode(query), ""))
    return MediaURL(url=url, platform=platform,
                    default_kind="audio" if platform in {"spotify", "yandex"} else None)

def find_media_url(text: str) -> MediaURL | None:
    found = LINK_RE.search(text)
    if found is None:
        return None
    return parse_media_url(found.group(0).rstrip(".,;!?)\u00bb"))

def cache_key(media: MediaURL, kind: str, owner_id: int | None = None) -> str:
    # Authenticated downloads cannot be reused across users.
    scope = str(owner_id) if owner_id is not None else "public"
    return hashlib.sha256(f"{scope}:{kind}:{media.url}".encode()).hexdigest()
