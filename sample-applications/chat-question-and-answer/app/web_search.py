# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import asyncio
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx
from langchain_core.documents import Document

from .read_only_web import PageFetchError, fetch_read_only_page
from .web_policy import WebRule, allowed_page

SEARCH_URL = "https://www.bing.com/search"
MAX_RESPONSE_BYTES = 1_000_000
MAX_ARTICLES = 3


class WebSearchError(RuntimeError):
    pass


@dataclass
class WebSearchResult:
    documents: list[Document]
    failures: int = 0


def validated_refinement(original: str, candidate: str) -> str | None:
    original_words = set(re.findall(r"[^\W_]+", original.casefold()))
    words = re.findall(r"[^\W_]+", candidate.casefold())
    if not words or len(words) > 12 or not set(words) <= original_words:
        return None
    result = " ".join(words)
    if result == " ".join(re.findall(r"[^\W_]+", original.casefold())):
        return None
    return result


async def search_web(query: str, client: httpx.AsyncClient, rules: list[WebRule]) -> WebSearchResult:
    if query.startswith("https://"):
        if not allowed_page(query, rules):
            raise WebSearchError("The requested URL is not allowed by your web settings.")
        try:
            page = await asyncio.to_thread(fetch_read_only_page, query)
        except PageFetchError as error:
            raise WebSearchError(str(error)) from error
        return WebSearchResult([page])

    try:
        async with client.stream("GET", SEARCH_URL, params={"q": query, "format": "rss"}) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise WebSearchError("Search response exceeded the size limit.")
        if b"<!DOCTYPE" in body.upper():
            raise WebSearchError("Search provider returned an unsupported response.")
        root = ET.fromstring(body)
    except (httpx.HTTPError, ET.ParseError) as error:
        raise WebSearchError("Web search failed; please try again.") from error
    links = [
        item.findtext("link", "").strip()
        for item in root.findall("./channel/item")[:MAX_ARTICLES]
    ]
    documents = []
    failures = 0
    for link in links:
        if not allowed_page(link, rules):
            failures += 1
            continue
        try:
            documents.append(await asyncio.to_thread(fetch_read_only_page, link))
        except PageFetchError:
            failures += 1
    if failures and not documents:
        raise WebSearchError("Search returned results, but none were allowed and readable under your web settings.")
    return WebSearchResult(documents, failures)
