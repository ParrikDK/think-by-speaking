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
a voice loop; the toggle only *partially* works on v4-pro — live-measured
2026-08-16: ~2.9k reasoning tokens with the toggle vs ~6.8k without).
The extra salvage-enrichment LLM call was deleted in v10; a local
plain-text wrap covers contract violations.

v12 (2026-08-16): two live-verified fixes to the tutor calls.
1. `max_tokens` 2048 → 8192: at 2048 the v4 models stochastically burn
   the budget on reasoning and complete with EMPTY content (~50% on the
   ~6.5k-char persona prompt) → every retry lands in the canned apology.
2. `thinking: disabled` REMOVED from the tutor calls: thinking-off +
   `response_format=json_object` returns empty content on v4 (9/9
   failures live; the v10-era "thinking OFF for latency" choice predates
   json_object). Thinking ON + json_object + a real budget completes
   reliably with valid JSON. Latency is ~15-60s per turn on both
   deepseek-v4-pro and deepseek-v4-flash (reasoning phase streams nothing
   — the voice loop lives on the Qwen realtime bridge, not this path).
The cheap nudge call (chat_reply_fast) still uses thinking-off — it is
plain text, best-effort, and the caller keeps the original reply on "".
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
# v12 (2026-08-16): used ONLY by the cheap nudge call — thinking-off +
# json_object returns empty content on v4 (live-verified), so the tutor
# calls leave thinking ON.
_THINKING_OFF = {"thinking": {"type": "disabled"}}

# Real JSON output mode — json_object + a real token budget is the reliable
# combo on v4 (see module docstring, v12 budget notes).
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
    """Coerce a parsed LLM dict into the contract's reply shape (v13:
    the grammar object became the debate feedback card)."""
    reply = str(parsed.get("reply") or parsed.get("text") or "").strip()
    if not reply:
        raise ValueError("LLM payload has empty reply")
    translation = str(parsed.get("translation") or "").strip()

    feedback = parsed.get("feedback")
    if not isinstance(feedback, dict):
        feedback = None
    else:
        fallacies = []
        for f in (feedback.get("fallacies") or []):
            if isinstance(f, dict):
                fallacies.append({
                    "type": str(f.get("type") or "other"),
                    "quote": str(f.get("quote") or ""),
                    "note": str(f.get("note") or ""),
                })
            if len(fallacies) >= 2:  # the contract caps at 2
                break
        feedback = {
            "stance": str(feedback.get("stance") or "partially_agree"),
            "score": int(feedback.get("score") or 50),
            "score_delta": int(feedback.get("score_delta") or 0),
            "counter": str(feedback.get("counter") or ""),
            "evidence": str(feedback.get("evidence") or ""),
            "next": str(feedback.get("next") or ""),
            "fallacies": fallacies,
            "structure": str(feedback.get("structure") or ""),
        }

    return {
        "reply": reply,
        "translation": translation,
        "feedback": feedback,
    }


def fallback_payload(language: str) -> dict:
    """Localized canned apology payload for total LLM failure.
    Uses error_message (system glitch) rather than silence_message (missed speech)
    so the user can distinguish "I didn't hear you" from "the system broke."
    """
    return {
        "reply": error_message(language),
        "translation": "",
        "feedback": None,
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
        max_tokens=8192,
        # v12 (2026-08-16): json_object + real budget + thinking ON.
        # thinking-off + json_object returns EMPTY content on v4
        # (live-verified 9/9); 2048 max_tokens burns to nothing on long
        # persona prompts. This combo completes reliably.
        response_format=_JSON_MODE,
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
        return {"reply": strip_markdown(content), "translation": "", "feedback": None}


async def chat_json(messages: list[dict], language: str = "en", native_language: str = "en") -> dict:
    """Strict-JSON tutor reply. Never raises — localized fallback on failure."""
    try:
        return await _complete_once(messages, language, native_language)
    except Exception as exc:
        logger.error("LLM failed after 3 attempts: {} — canned fallback", exc)
        return fallback_payload(language)


async def chat_reply_fast(messages: list[dict]) -> str:
    """Reply-only regeneration (plain text) — used for the language-drift
    nudge retry so it costs a fraction of a full turn.

    v12 (2026-08-16): max_tokens raised 200 → 2048 — at 200 the v4-flash
    reasoning always consumed the budget and the nudge silently never
    returned text (live-verified). The caller keeps the original reply on
    "" either way.

    Returns the trimmed text, or "" on failure (caller keeps the original).
    """
    try:
        response = await _get_client().chat.completions.create(
            model=get_settings().deepseek_model_fast,
            messages=messages,
            temperature=0.4,
            max_tokens=2048,
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
                max_tokens=8192,
                stream=True,
                # v12 (2026-08-16): json_object + real budget + thinking ON
                # — see _complete_once. The reasoning phase streams no
                # content, so the first token is late but guaranteed.
                response_format=_JSON_MODE,
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
        final = {"reply": strip_markdown(text), "translation": "", "feedback": None}
    if final is None:
        final = fallback_payload(language)
        # Ensure the streamed text matches what the complete event will carry:
        # nothing was emitted (or partial junk was) — emit the fallback reply.
        if not emitted_len:
            yield final["reply"]
        yield {**final, "__llm_failed": True}
        return
    yield final
