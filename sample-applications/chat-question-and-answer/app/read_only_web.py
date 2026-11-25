# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import http.client
import ipaddress
import socket
import time
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from langchain_core.documents import Document

MAX_PAGE_BYTES = 1_000_000
MAX_EXTRACT_CHARS = 900


class PageFetchError(RuntimeError):
    pass


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "form", "nav", "footer", "header", "noscript"}:
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "form", "nav", "footer", "header", "noscript"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data):
        if not self.ignored and data.strip():
            self.parts.append(data.strip())


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str):
        super().__init__(host, port=443, timeout=10, context=httpx.create_ssl_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except (OSError, ValueError):
            sock.close()
            raise


def normalize_page_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.port not in (None, 443)
            or parsed.query or parsed.fragment
            or any(ord(char) < 33 or ord(char) == 127 for char in url)
        ):
            raise ValueError("Unsupported URL")
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("IP literal URLs are not allowed")
        if not host or "." not in host:
            raise ValueError("A public hostname is required")
        path = quote(parsed.path or "/", safe="/%:@-._~!$&'*,;=+")
        return urlunsplit(("https", host, path, "", ""))
    except (ValueError, UnicodeError) as error:
        raise PageFetchError("The page URL is not an allowed public HTTPS URL.") from error


def _validated_target(url: str) -> tuple[str, str, str]:
    try:
        safe_url = normalize_page_url(url)
        host = urlsplit(safe_url).hostname
        if host is None:
            raise ValueError("A public hostname is required")
        addresses = {info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        if not addresses or any(
            not (ipaddress.ip_address(address).is_global and not ipaddress.ip_address(address).is_multicast)
            for address in addresses
        ):
            raise ValueError("Non-public address")
        return host, sorted(addresses)[0], safe_url
    except (ValueError, OSError) as error:
        raise PageFetchError("The page URL is not an allowed public HTTPS URL.") from error


def fetch_read_only_page(url: str) -> Document:
    host, address, safe_url = _validated_target(url)
    path = urlsplit(safe_url).path or "/"
    connection = _PinnedHTTPSConnection(host, address)
    try:
        connection.request("GET", path, headers={
            "Host": host,
            "User-Agent": "ChatQnA/1.0 (read-only web retrieval)",
            "Accept": "text/html, text/plain",
            "Accept-Encoding": "identity",
        })
        response = connection.getresponse()
        content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
        if response.status != 200 or content_type not in {"text/html", "text/plain"}:
            raise PageFetchError(f"Page could not be read (HTTP {response.status}, {content_type or 'unknown type'}).")
        deadline = time.monotonic() + 15
        content = bytearray()
        while len(content) <= MAX_PAGE_BYTES:
            if time.monotonic() >= deadline:
                raise PageFetchError("Page retrieval timed out.")
            chunk = response.read1(min(16384, MAX_PAGE_BYTES + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
        page_truncated = len(content) > MAX_PAGE_BYTES
        content = content[:MAX_PAGE_BYTES]
        charset = response.headers.get_content_charset() or "utf-8"
        text = content.decode(charset, errors="replace")
    except (OSError, http.client.HTTPException, LookupError) as error:
        raise PageFetchError("Could not retrieve the page securely.") from error
    finally:
        connection.close()

    if content_type == "text/html":
        parser = _PageText()
        parser.feed(text)
        text = " ".join(parser.parts)
    else:
        text = " ".join(text.split())
    if not text:
        raise PageFetchError("The page contained no readable text.")
    excerpt = text[:MAX_EXTRACT_CHARS]
    if page_truncated or len(text) > MAX_EXTRACT_CHARS:
        excerpt += " [Excerpt truncated]"
    return Document(page_content=excerpt, metadata={"source": safe_url})
