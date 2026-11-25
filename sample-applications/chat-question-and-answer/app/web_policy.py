# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import json
import re
from typing import Literal, TypedDict

from sqlalchemy import text

from .account_store import _ensure_tables, _get_engine
from .read_only_web import PageFetchError, normalize_page_url


class WebRule(TypedDict):
    kind: Literal["url", "phrase"]
    effect: Literal["allow", "deny"]
    value: str


def normalize_rules(rules: list[WebRule]) -> list[WebRule]:
    if len(rules) > 100:
        raise ValueError("At most 100 web rules are allowed.")
    normalized: list[WebRule] = []
    seen = set()
    for rule in rules:
        value = rule["value"].strip()
        if rule["kind"] not in ("url", "phrase") or rule["effect"] not in ("allow", "deny"):
            raise ValueError("Invalid web rule.")
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("A rule value is required and cannot contain control characters.")
        if rule["kind"] == "url":
            if len(value) > 2048:
                raise ValueError("URL is too long.")
            try:
                value = normalize_page_url(value)
            except PageFetchError as error:
                raise ValueError(str(error)) from error
        elif len(value) > 160 or "://" in value:
            raise ValueError("Search phrases must be at most 160 characters and cannot contain URLs.")
        key = (rule["kind"], rule["effect"], value.casefold() if rule["kind"] == "phrase" else value)
        if key in seen:
            raise ValueError("Duplicate web rule.")
        seen.add(key)
        normalized.append({"kind": rule["kind"], "effect": rule["effect"], "value": value})
    return normalized


async def initialize_web_policy(connection) -> None:
    await connection.execute(text("""
        CREATE TABLE IF NOT EXISTS chat_user_web_rules (
            user_id BIGINT PRIMARY KEY REFERENCES chat_users(id) ON DELETE CASCADE,
            rules JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))


async def get_web_rules(user_id: int) -> list[WebRule]:
    await _ensure_tables()
    async with _get_engine().connect() as connection:
        result = await connection.execute(
            text("SELECT rules FROM chat_user_web_rules WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        return result.scalar_one_or_none() or []


async def save_web_rules(user_id: int, rules: list[WebRule]) -> list[WebRule]:
    rules = normalize_rules(rules)
    await _ensure_tables()
    async with _get_engine().begin() as connection:
        await connection.execute(text("""
            INSERT INTO chat_user_web_rules (user_id, rules)
            VALUES (:user_id, CAST(:rules AS JSONB))
            ON CONFLICT (user_id) DO UPDATE SET rules = EXCLUDED.rules, updated_at = NOW()
        """), {"user_id": user_id, "rules": json.dumps(rules)})
    return rules


def allowed_page(url: str, rules: list[WebRule]) -> bool:
    try:
        normalized = normalize_page_url(url)
    except PageFetchError:
        return False
    allowed = any(rule["kind"] == "url" and rule["effect"] == "allow" and rule["value"] == normalized for rule in rules)
    denied = any(rule["kind"] == "url" and rule["effect"] == "deny" and rule["value"] == normalized for rule in rules)
    return allowed and not denied


def select_web_query(question: str, rules: list[WebRule]) -> str:
    lowered = question.casefold()
    if any(rule["kind"] == "phrase" and rule["effect"] == "deny" and rule["value"].casefold() in lowered for rule in rules):
        raise ValueError("Web access is blocked by a denied phrase in Settings.")
    urls = re.findall(r"https://[^\s<>\"']+", question, flags=re.IGNORECASE)
    if urls:
        if len(urls) != 1:
            raise ValueError("Ask about one allowed web URL at a time.")
        url = urls[0]
        while url:
            try:
                normalized = normalize_page_url(url)
            except PageFetchError:
                normalized = None
            if normalized and any(
                rule["kind"] == "url" and rule["effect"] == "deny" and rule["value"] == normalized
                for rule in rules
            ):
                raise ValueError("The requested URL is not allowed by your web settings.")
            if normalized and allowed_page(url, rules):
                return normalized
            if url[-1] not in ".,;)]":
                break
            url = url[:-1]
        raise ValueError("The requested URL is not allowed by your web settings.")
    if not any(rule["kind"] == "url" and rule["effect"] == "allow" for rule in rules):
        raise ValueError("Add at least one allowed URL in Settings before using web search.")
    phrases = [
        rule["value"] for rule in rules
        if rule["kind"] == "phrase" and rule["effect"] == "allow"
        and rule["value"].casefold() in lowered
    ]
    if not phrases:
        raise ValueError("No allowed search phrase matched. Configure web rules in Settings.")
    return max(phrases, key=len)
