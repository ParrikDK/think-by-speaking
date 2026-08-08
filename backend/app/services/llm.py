"""DeepSeek LLM service (OpenAI-compatible, https://api.deepseek.com).

- Non-streaming strict-JSON completion with tenacity (3 attempts).
- Real token streaming via stream=True for /api/chat/stream: the raw JSON
  is accumulated while the "reply" field's value is extracted incrementally
  and yielded as tokens as it arrives.
- Robust JSON extraction (plain → markdown fence → brace slice).
- Plain-text salvage: when the model ignores the JSON contract, its words
  are kept as the reply (local wrap — no extra network call).
- Localized canned fallback payload when all attempts fail.

v10 (2026-08-06): DeepSeek v4 models. Thinking mode is explicitly DISABLED
on every call (v4 defaults to thinking ON — first-token latency matters in
a voice loop) and the tutor calls use the real JSON output mode
(response_format json_object — v4 fixed the old empty-content bug that
made v9 avoid it). The extra salvage-enrichment LLM call was deleted with
it: json_object mode makes contract violations rare, and a local
plain-text wrap covers the remainder.
"""
import json
import re
from typing import AsyncGenerator

from loguru import logger
from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import get_settings
from ..prompts.tutor import error_message

_client: AsyncOpenAI | None = None

# v4 defaults to thinking mode ON; the OpenAI-format toggle must go through
# extra_body (https://api-docs.deepseek.com/guides/thinking_mode).
_THINKING_OFF = {"thinking": {"type": "disabled"}}

# Real JSON output mode — guaranteed valid JSON on v4 (both models ✓).
_JSON_MODE = {"type": "json_object"}


def _get_client(force_new: bool = False) -> AsyncOpenAI:
    """Lazily built so importing the module never needs an API key.

    Pass *force_new=True* to recreate the client (used when DeepSeek
    transiently rejects an otherwise-valid API key with 401).
    """
    global _client
    if _client is None or force_new:
        settings = get_settings()
        _client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url="https://api.deepseek.com",
            timeout=settings.llm_timeout_seconds,
        )
    return _client


# ── Robust JSON extraction ───────────────────────────────────────────

def extract_json(raw: str) -> dict:
    """Extract a JSON object from an LLM response, tolerating fences/prose."""
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("empty LLM response")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"no JSON object found in LLM response ({len(raw)} chars)")


def normalize_payload(parsed: dict) -> dict:
    """Coerce a parsed LLM dict into the contract's reply shape."""
    reply = str(parsed.get("reply") or parsed.get("text") or "").strip()
    if not reply:
        raise ValueError("LLM payload has empty reply")
    translation = str(parsed.get("translation") or "").strip()

    grammar = parsed.get("grammar")
    if not isinstance(grammar, dict):
        grammar = None
    else:
        grammar = {
            "is_correct": bool(grammar.get("is_correct", True)),
            "corrected_text": str(grammar.get("corrected_text") or ""),
            "explanation": str(grammar.get("explanation") or ""),
        }

    return {
        "reply": reply,
        "translation": translation,
        "grammar": grammar,
    }


def fallback_payload(language: str) -> dict:
    """Localized canned apology payload for total LLM failure.
    Uses error_message (system glitch) rather than silence_message (missed speech)
    so the user can distinguish "I didn't hear you" from "the system broke."
    """
    return {
        "reply": error_message(language),
        "translation": "",
        "grammar": None,
    }


# ── Markdown stripping (replies are read aloud by TTS — asterisks leak) ──
_MD_PATTERNS = [
    (re.compile(r'\*\*(.+?)\*\*'), r'\1'),        # **bold** → text
    (re.compile(r'\*([^*]{3,}?)\*'), r'\1'),       # *italic/action* → text (3+ chars)
    (re.compile(r'__(.+?)__'), r'\1'),             # __bold__ → text
    (re.compile(r'`{1,3}[^`]+`{1,3}'), ''),        # `code` / ```code``` → remove
    (re.compile(r'^#{1,6}\s+', re.MULTILINE), ''), # ## headers → remove
    (re.compile(r'^\[.*?\]\(.*?\)', re.MULTILINE), ''), # [text](url) → remove
    (re.compile(r'!\[.*?\]\(.*?\)'), ''),           # ![alt](url) → remove
    (re.compile(r'^>\s+', re.MULTILINE), ''),       # > blockquote → remove
    (re.compile(r'^[-*]\s+', re.MULTILINE), ''),    # - / * bullet lists → remove
    (re.compile(r'^\d+[.)]\s+', re.MULTILINE), ''), # 1. 2. 3) numbered lists → remove
    (re.compile(r'^---+$', re.MULTILINE), ''),      # --- hr → remove
    (re.compile(r'^\|.*\|$', re.MULTILINE), ''),    # | table | rows → remove
    (re.compile(r'\n{3,}'), '\n\n'),                # 3+ newlines → 2
]


def strip_markdown(text: str) -> str:
    """Remove Markdown formatting from AI tutor responses."""
    if not text:
        return text
    for pattern, replacement in _MD_PATTERNS:
        text = pattern.sub(replacement, text)
    return text.strip()


def _strip_payload_markdown(payload: dict) -> dict:
    """Apply markdown stripping to a normalized payload (reply + translation)."""
    return {
        **payload,
        "reply": strip_markdown(payload.get("reply", "")),
        "translation": strip_markdown(payload.get("translation", "")),
    }


# ── Non-streaming completion (3 attempts via tenacity) ───────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
async def _complete_once(messages: list[dict], language: str = "en", native_language: str = "en") -> dict:
    settings = get_settings()
    response = await _get_client().chat.completions.create(
        model=settings.deepseek_model,
        messages=messages,
        temperature=0.4,
        max_tokens=2048,
        # v10 (2026-08-06): real JSON output mode — v4 fixed the empty-content
        # bug that made v9 avoid json_object; thinking OFF for latency.
        response_format=_JSON_MODE,
        extra_body=_THINKING_OFF,
    )
    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise ValueError("empty LLM response")
    try:
        return _strip_payload_markdown(normalize_payload(extract_json(content)))
    except ValueError:
        if content.lstrip().startswith("{") or '"reply"' in content:
            # The model ATTEMPTED JSON but produced invalid JSON (e.g.
            # unescaped quotes inside the reply: '{"reply": "He said "hello""}')
            # — salvaging the raw text would put '{ "reply": ... }' braces in
            # the UI and have TTS read them aloud (live-observed 2026-08-02).
            # Retry instead (tenacity); worst case the glitch fallback.
            logger.warning("LLM returned invalid JSON-looking text ({} chars) — retrying, not salvaging", len(content))
            raise ValueError("invalid JSON attempt — retry")
        # The model ignored the strict-JSON contract and replied in plain
        # conversational text. Salvage the words as the reply rather than
        # failing into the canned glitch fallback. v10: local wrap only —
        # the extra translation-enrichment call was deleted with the move
        # to json_object mode (contract violations are now rare).
        logger.warning("LLM returned non-JSON text ({} chars) — salvaging as reply", len(content))
        return {"reply": strip_markdown(content), "translation": "", "grammar": None}


async def chat_json(messages: list[dict], language: str = "en", native_language: str = "en") -> dict:
    """Strict-JSON tutor reply. Never raises — localized fallback on failure."""
    try:
        return await _complete_once(messages, language, native_language)
    except Exception as exc:
        logger.error("LLM failed after 3 attempts: {} — canned fallback", exc)
        return fallback_payload(language)


async def chat_reply_fast(messages: list[dict]) -> str:
    """Reply-only regeneration (plain text, small max_tokens) — used for the
    language-drift nudge retry so it costs a fraction of a full turn.

    Returns the trimmed text, or "" on failure (caller keeps the original).
    """
    try:
        response = await _get_client().chat.completions.create(
            model=get_settings().deepseek_model_fast,
            messages=messages,
            temperature=0.4,
            max_tokens=200,
            extra_body=_THINKING_OFF,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("Fast nudge reply failed: {} — keeping original reply", exc)
        return ""


# ── Streaming completion (real tokens of the "reply" field) ──────────

def _extract_reply_prefix(buffer: str) -> str:
    """Value-so-far of the top-level "reply" key in a partial JSON string."""
    m = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)', buffer)
    if not m:
        return ""
    return m.group(1)


def _unescape_partial(s: str) -> str:
    """Best-effort unescape of a partial JSON string value."""
    try:
        return json.loads(f'"{s}"')
    except json.JSONDecodeError:
        # Trailing backslash / incomplete escape — drop the tail and retry
        try:
            return json.loads(f'"{s.rstrip(chr(92))}"')
        except json.JSONDecodeError:
            return s


async def chat_json_stream(
    messages: list[dict], language: str = "en", native_language: str = "en"
) -> AsyncGenerator[str | dict, None]:
    """Stream real LLM tokens of the reply text, then yield the final payload dict.

    Yields str reply-text deltas as they arrive, then exactly one dict —
    the normalized payload (same shape as chat_json).
    """
    settings = get_settings()
    buffer = ""
    emitted_len = 0
    final: dict | None = None

    # Streaming has no tenacity decorator, so we retry the connection manually.
    # Unlike chat_json (3 retries on the full call), we only retry stream
    # creation — not mid-stream recovery (that would require re-sending the
    # entire context to the API and could confuse the partial-buffer extraction).
    _last_exc: Exception | None = None
    for attempt in range(1, settings.llm_stream_retries + 1):
        try:
            stream = await _get_client().chat.completions.create(
                model=settings.deepseek_model,
                messages=messages,
                temperature=0.4,
                max_tokens=2048,
                stream=True,
                # v10 (2026-08-06): json_object composes with streaming on v4
                # (tokens still arrive incrementally); thinking OFF for latency.
                response_format=_JSON_MODE,
                extra_body=_THINKING_OFF,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                content = getattr(delta, "content", None) if delta else None
                if not content:
                    continue
                buffer += content
                current = _unescape_partial(_extract_reply_prefix(buffer))
                if len(current) > emitted_len:
                    token = current[emitted_len:]
                    emitted_len = len(current)
                    yield token
            if not buffer:
                # DeepSeek intermittently completes with an empty stream (no
                # exception, no chunks) — treat it as a failed attempt so the
                # retry loop gives the model another chance.
                raise RuntimeError("LLM stream returned no content")
            # Stream completed without exception — break out of retry loop.
            break
        except Exception as exc:
            _last_exc = exc
            # DeepSeek intermittently returns 401 for valid keys — recreate the
            # client on auth errors so the next attempt has a fresh connection.
            _exc_str = str(exc)
            if "401" in _exc_str or "authentication" in _exc_str.lower() or "invalid" in _exc_str.lower():
                _get_client(force_new=True)
                logger.warning("[LLM STREAM RETRY {}/{}] recreated client after auth error", attempt, settings.llm_stream_retries)
            logger.warning("LLM stream attempt {}/{} failed [{}]: {}", attempt, settings.llm_stream_retries, type(exc).__name__, exc)
            if attempt < settings.llm_stream_retries:
                import asyncio
                await asyncio.sleep(1.0 * attempt)  # 1s, 2s, 3s...
            buffer = ""  # reset partial buffer on retry
            emitted_len = 0

    if _last_exc is not None:
        logger.error("LLM stream failed after {} attempts [{}]: {}", settings.llm_stream_retries, type(_last_exc).__name__, _last_exc)

    try:
        final = _strip_payload_markdown(normalize_payload(extract_json(buffer))) if buffer.strip() else None
    except ValueError:
        final = None
    if final is None and buffer.strip():
        # The model ignored the JSON contract and spoke plain text — salvage
        # it as the reply (the UI streams whatever text remains un-emitted).
        # v10: local wrap only — the translation-enrichment call was deleted.
        text = buffer.strip()
        if len(text) > emitted_len:
            yield text[emitted_len:]
        final = {"reply": strip_markdown(text), "translation": "", "grammar": None}
    if final is None:
        final = fallback_payload(language)
        # Ensure the streamed text matches what the complete event will carry:
        # nothing was emitted (or partial junk was) — emit the fallback reply.
        if not emitted_len:
            yield final["reply"]
        yield {**final, "__llm_failed": True}
        return
    yield final
