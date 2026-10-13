from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
TRACKING_PREFIXES = ("utm_",)


def canonicalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("only HTTP(S) source URLs are supported")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("source URL must have a hostname and no embedded credentials")

    hostname = parsed.hostname.encode("idna").decode("ascii").lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    port = parsed.port
    if port is not None and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"

    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_KEYS
        and not any(key.lower().startswith(prefix) for prefix in TRACKING_PREFIXES)
    ]
    # Repeated query keys and path slashes can be content-bearing. Do not reorder
    # or collapse them; conservative identity is safer than merging distinct pages.
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), hostname, path, urlencode(query), ""))


def normalize_text(value: str) -> str:
    without_nulls = value.replace("\x00", "")
    lines = without_nulls.replace("\r\n", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()
