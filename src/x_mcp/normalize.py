"""Explicit projections keep provider metadata and untrusted instructions out of control flow."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

from .errors import XError


def timestamp(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if isinstance(value, (float, int)):
            dt = datetime.fromtimestamp(value, UTC)
        elif isinstance(value, datetime):
            dt = value
        else:
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                dt = parsedate_to_datetime(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
        return number if number >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def public_user(raw: dict[str, Any], *, session: bool = False) -> bool:
    # A logged-in request can see protected accounts; unknown is not permission.
    return raw.get("protected") is False if session else raw.get("protected") is not True


def user(raw: dict[str, Any], *, session: bool = False) -> dict[str, Any]:
    if not public_user(raw, session=session):
        raise XError("PUBLIC_ONLY", "Protected or unverified account data is excluded.")
    handle = raw.get("screen_name") or raw.get("username")
    if not isinstance(handle, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
        raise XError("PROVIDER_CHANGED", "Provider profile format is not recognized.")
    return {
        "kind": "user",
        "id": str(raw["id"]),
        "handle": handle,
        "url": f"https://x.com/{handle}",
        "name": raw.get("name") or raw.get("displayname"),
        "text": raw.get("description") or raw.get("rawDescription") or "",
        "created_at": timestamp(raw.get("joined") or raw.get("created")),
        "metrics": {
            "followers": count(raw.get("followers", raw.get("followersCount"))),
            "following": count(raw.get("following", raw.get("friendsCount"))),
            "posts": count(raw.get("statuses", raw.get("statusesCount"))),
        },
        "location": raw.get("location"),
        "website": raw.get("website"),
        "avatar_url": safe_url(raw.get("avatar_url") or raw.get("profileImageUrl")),
        "verification": raw.get("verification"),
        "about_account": raw.get("about_account"),
    }


def safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    return None


def media_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    result = []
    source = value.get("all")
    if not isinstance(source, list):
        source = [
            {"type": kind, **item}
            for kind in ("photos", "videos", "animated")
            for item in value.get(kind, [])
            if isinstance(item, dict)
        ]
    for item in source[:16]:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "type": item.get("type"),
                "url": safe_url(item.get("url")),
                "thumbnail_url": safe_url(item.get("thumbnail_url") or item.get("thumbnailUrl")),
                "alt_text": item.get("altText") or item.get("alt_text"),
                "width": count(item.get("width")),
                "height": count(item.get("height")),
            }
        )
    return result


def post(raw: dict[str, Any], *, session: bool = False, depth: int = 0) -> dict[str, Any]:
    if raw.get("type") == "tombstone" or not raw.get("id"):
        raise XError("NOT_FOUND", "Post is deleted or unavailable.")
    author = user(raw.get("author") or raw.get("user") or {}, session=session)
    ident = str(raw["id"])
    if not re.fullmatch(r"[0-9]{1,20}", ident):
        raise XError("PROVIDER_CHANGED", "Provider post ID is invalid.")
    text = raw.get("text", raw.get("rawContent", ""))
    result = {
        "kind": "post",
        "id": ident,
        "url": f"https://x.com/{author['handle']}/status/{ident}",
        "author": {k: author[k] for k in ("id", "handle", "name")},
        "created_at": timestamp(
            raw.get("created_timestamp") or raw.get("created_at") or raw.get("date")
        ),
        "text": text if isinstance(text, str) else "",
        "metrics": {
            "likes": count(raw.get("likes", raw.get("likeCount"))),
            "reposts": count(raw.get("reposts", raw.get("retweetCount"))),
            "replies": count(raw.get("replies", raw.get("replyCount"))),
            "quotes": count(raw.get("quotes", raw.get("quoteCount"))),
            "views": count(raw.get("views", raw.get("viewCount"))),
        },
        "language": raw.get("lang"),
        "reply_to": str(raw["inReplyToTweetId"])
        if raw.get("inReplyToTweetId")
        else raw.get("replying_to"),
        "conversation_id": str(raw["conversationId"]) if raw.get("conversationId") else None,
        "media": media_items(raw.get("media")),
        "links": [
            url
            for item in raw.get("links", [])
            if (url := safe_url(item.get("url") if isinstance(item, dict) else item))
        ],
        "hashtags": raw.get("hashtags", []),
    }
    quote = raw.get("quote") or raw.get("quotedTweet")
    article = raw.get("article")
    if isinstance(article, dict):
        content = article.get("content") or {}
        blocks = content.get("blocks") or []
        entities = content.get("entityMap") or []
        # Retain text and markdown evidence, excluding layout/color metadata.
        result["article"] = {
            "id": str(article.get("id", "")),
            "title": article.get("title"),
            "preview_text": article.get("preview_text"),
            "created_at": timestamp(article.get("created_at")),
            "modified_at": timestamp(article.get("modified_at")),
            "blocks": [
                {"type": b.get("type"), "text": b.get("text", "")}
                for b in blocks
                if isinstance(b, dict)
            ],
            "markdown": [
                e["value"]["data"]["markdown"]
                for e in entities
                if isinstance(e, dict)
                and isinstance(e.get("value"), dict)
                and isinstance(e["value"].get("data"), dict)
                and isinstance(e["value"]["data"].get("markdown"), str)
            ],
        }
    if depth == 0 and isinstance(quote, dict):
        try:
            result["quote"] = post(quote, session=session, depth=1)
        except XError:
            result["quote_unavailable"] = True
    return result


def trend(raw: dict[str, Any]) -> dict[str, Any]:
    name = raw.get("name") or raw.get("trend_name") or raw.get("text")
    if not isinstance(name, str):
        raise XError("PROVIDER_CHANGED", "Provider trend format is not recognized.")
    from urllib.parse import quote

    return {
        "kind": "trend",
        "id": name,
        "text": name,
        "url": f"https://x.com/search?q={quote(name, safe='')}",
        "post_count": count(raw.get("tweet_count", raw.get("tweetCount"))),
        "description": raw.get("description") or raw.get("meta_description"),
    }


def compact(item: dict[str, Any], detail: str) -> dict[str, Any]:
    if detail == "full":
        return dict(item)
    fields = {
        "kind",
        "id",
        "url",
        "author",
        "handle",
        "name",
        "created_at",
        "text",
        "metrics",
        "post_count",
    }
    result = {k: v for k, v in item.items() if k in fields}
    if isinstance(result.get("metrics"), dict) and item.get("kind") == "post":
        result["metrics"] = {
            k: v for k, v in result["metrics"].items() if k in {"likes", "reposts", "replies"}
        }
    if isinstance(result.get("text"), str) and len(result["text"]) > 600:
        result["text"] = result["text"][:600]
        result["text_truncated"] = True
    if item.get("media"):
        result["media_count"] = len(item["media"])
    if item.get("article"):
        result["has_article"] = True
    return result
