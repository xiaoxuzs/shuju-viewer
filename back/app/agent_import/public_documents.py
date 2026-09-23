"""Operator-approved public documents; pinned public IP, no redirect or queries."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import socket
import ssl
from html.parser import HTMLParser
from urllib.parse import urlsplit


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def public_target(url: str) -> tuple[str, str]:
    value = urlsplit(url)
    if (value.scheme != "https" or not value.hostname or value.username or value.password
            or value.query or value.fragment or value.port not in {None, 443}):
        raise ValueError("Public documents require an exact HTTPS URL without credentials or queries")
    addresses = {entry[4][0] for entry in socket.getaddrinfo(value.hostname, 443, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Public documents cannot access non-public networks")
    return value.hostname, sorted(addresses)[0]


class _PinnedHttps(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str) -> None:
        super().__init__(host, timeout=15, context=ssl.create_default_context())
        self.address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self.address, 443), self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class PublicDocuments:
    def __init__(self, catalog: dict[str, str]) -> None:
        if not isinstance(catalog, dict) or len(catalog) > 30 or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in catalog.items()
        ):
            raise ValueError("Invalid public document catalog")
        self.catalog = dict(catalog)

    def read(self, document_id: str) -> dict:
        if document_id not in self.catalog:
            raise ValueError("Document is not in the approved catalog")
        url = self.catalog[document_id]
        host, address = public_target(url)
        connection = _PinnedHttps(host, address)
        try:
            connection.request("GET", urlsplit(url).path or "/", headers={"Accept": "text/plain, text/html", "User-Agent": "Viewer-public-document/1"})
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError("Public document fetch failed; redirects are not followed")
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].lower()
            if content_type not in {"text/plain", "text/html", "application/json"}:
                raise ValueError("Document media type is not allowed")
            raw = response.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                raise ValueError("Document exceeds byte budget")
            text = raw.decode("utf-8", errors="replace")
            if content_type == "text/html":
                parser = _Text()
                parser.feed(text)
                text = "\n".join(parser.parts)
            return {"kind": "public_document", "url": url, "document_id": document_id,
                    "sha256": hashlib.sha256(raw).hexdigest(), "etag": response.getheader("ETag"),
                    "last_modified": response.getheader("Last-Modified"), "text": text[:24_000],
                    "truncated": len(text) > 24_000}
        finally:
            connection.close()
