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
    "tiktok.com": "tiktok", "www.tiktok.com": "tiktok", "m.tiktok.com": "tiktok",
    "vm.tiktok.com": "tiktok", "vt.tiktok.com": "tiktok",
    "open.spotify.com": "spotify",
    "instagram.com": "instagram", "www.instagram.com": "instagram",
    "pinterest.com": "pinterest", "www.pinterest.com": "pinterest",
    "pin.it": "pinterest",
    "deezer.com": "deezer", "www.deezer.com": "deezer",
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
    if platform == "deezer" and not re.fullmatch(r"/(?:[a-z]{2}/)?track/[0-9]+/?", parsed.path):
        raise InvalidMediaURL("Deezer: поддерживаются ссылки на отдельные треки.")
    if platform == "instagram" and not re.fullmatch(r"/(?:p|reels?|tv)/[A-Za-z0-9_-]+/?", parsed.path):
        raise InvalidMediaURL("Instagram: поддерживаются ссылки на публикации, Reels и видео.")
    if platform == "tiktok":
        if host in {"vm.tiktok.com", "vt.tiktok.com"}:
            valid = bool(re.fullmatch(r"/[A-Za-z0-9_-]+/?", parsed.path))
        else:
            valid = bool(
                re.fullmatch(r"/@[A-Za-z0-9._-]+/video/[0-9]+/?", parsed.path)
                or re.fullmatch(r"/t/[A-Za-z0-9_-]+/?", parsed.path)
            )
        if not valid:
            raise InvalidMediaURL(
                "TikTok: пришлите ссылку на отдельное видео, не на профиль или ленту."
            )
    if platform == "pinterest" and not (host == "pin.it" or
        re.fullmatch(r"/pin/[0-9]+/?", parsed.path)):
        raise InvalidMediaURL("Pinterest: поддерживаются ссылки на отдельные пины.")
    if platform == "deezer":
        track_id = parsed.path.rstrip("/").split("/")[-1]
        url = f"https://www.deezer.com/track/{track_id}"
    elif platform == "spotify":
        if not re.fullmatch(r"/track/[A-Za-z0-9]{22}/?", parsed.path):
            raise InvalidMediaURL("Spotify: поддерживаются только ссылки на отдельные треки.")
        url = f"https://open.spotify.com{parsed.path.rstrip('/')}"
    elif platform == "instagram":
        # Link-sharing and Instagram-specific query parameters are not needed
        # to fetch the same Reel and should not create separate cache entries.
        segments = parsed.path.strip("/").split("/")
        kind, shortcode = segments[0], segments[1]
        if kind == "reels":
            kind = "reel"
        url = f"https://www.instagram.com/{kind}/{shortcode}/"
    elif platform == "tiktok":
        # Strip tracking tokens, leave shortlinks untouched for yt-dlp's
        # canonical redirect resolution. Full video links get stable hosts.
        clean_host = host if host in {"vm.tiktok.com", "vt.tiktok.com"} else "www.tiktok.com"
        url = f"https://{clean_host}{parsed.path.rstrip('/')}"
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
                    default_kind="audio" if platform in {"spotify", "deezer", "yandex"} else None)

def short_video_label(raw_url: str) -> str | None:
    """Present a short-form video workflow without an extra network request."""
    parsed = urlsplit(raw_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if re.fullmatch(r"/shorts/[A-Za-z0-9_-]{11}/?", path):
            return "YouTube Shorts"
    if host in {"instagram.com", "www.instagram.com"}:
        if re.fullmatch(r"/reels?/[A-Za-z0-9_-]+/?", path):
            return "Instagram Reels"
        if re.fullmatch(r"/(?:p|tv)/[A-Za-z0-9_-]+/?", path):
            return "Instagram"
    if HOSTS.get(host) == "tiktok":
        return "TikTok"
    return None


def find_media_url(text: str) -> MediaURL | None:
    found = LINK_RE.search(text)
    if found is None:
        return None
    return parse_media_url(found.group(0).rstrip(".,;!?)\u00bb"))

def cache_key(media: MediaURL, kind: str, owner_id: int | None = None) -> str:
    # Authenticated downloads cannot be reused across users.
    scope = str(owner_id) if owner_id is not None else "public"
    return hashlib.sha256(f"{scope}:{kind}:{media.url}".encode()).hexdigest()
