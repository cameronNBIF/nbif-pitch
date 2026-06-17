def extract_domain(url: str) -> str:
    """Extract the root domain from a URL string."""
    if not url:
        return ""
    url = url.lower().strip()
    for prefix in ("https://", "http://", "www."):
        if url.startswith(prefix):
            url = url[len(prefix):]
    url = url.split("/")[0]
    return url
