"""Tests for app.services.llm — JSON extraction, payload normalization, fallback."""

import json
import pytest
from app.services.llm import (
    extract_json,
    normalize_payload,
    fallback_payload,
    _extract_reply_prefix,
    _unescape_partial,
)


# ── extract_json ─────────────────────────────────────────────────────────

class TestExtractJson:
    """extract_json: parse LLM output into a dict."""

    def test_valid_json(self):
        """Plain JSON string → parsed dict."""
        raw = '{"reply": "hello", "translation": ""}'
        result = extract_json(raw)
        assert result == {"reply": "hello", "translation": ""}

    def test_markdown_fenced_json(self):
        """Markdown-fenced ```json … ``` block → parsed dict."""
        raw = '```json\n{"reply": "hello", "translation": ""}\n```'
        result = extract_json(raw)
        assert result == {"reply": "hello", "translation": ""}

    def test_markdown_fence_no_language(self):
        """Fenced block without language tag → parsed dict."""
        raw = '```\n{"reply": "hi"}\n```'
        result = extract_json(raw)
        assert result == {"reply": "hi"}

    def test_brace_sliced_json(self):
        """Text with JSON-like braces inside prose → brace-sliced."""
        raw = "Sure! Here is the JSON: {\"reply\": \"hello\"} Hope that helps."
        result = extract_json(raw)
        assert result == {"reply": "hello"}

    def test_empty_string_raises(self):
        """Empty string → ValueError."""
        with pytest.raises(ValueError, match="empty LLM response"):
            extract_json("")

    def test_none_string_raises(self):
        """Falsy input (None stripped to empty) → ValueError."""
        with pytest.raises(ValueError, match="empty LLM response"):
            extract_json(None)  # type: ignore[arg-type]

    def test_non_json_string_raises(self):
        """Non-JSON string with no braces → ValueError."""
        with pytest.raises(ValueError, match="no JSON object found"):
            extract_json("This is just plain text without any JSON.")

    def test_invalid_json_with_braces_raises(self):
        """Malformed JSON inside braces → ValueError."""
        with pytest.raises(ValueError, match="no JSON object found"):
            extract_json('{"reply": "hello"');

    def test_markdown_with_prose_before_json(self):
        """Markdown with text before fenced code → parsed dict."""
        raw = 'Here you go:\n```json\n{"reply": "good morning", "translation": "早安"}\n```'
        result = extract_json(raw)
        assert result == {"reply": "good morning", "translation": "早安"}

    def test_markdown_with_trailing_text(self):
        """Markdown fenced code with trailing text → still extracts correctly."""
        raw = '```json\n{"reply": "hello"}\n```\nSome closing words.'
        result = extract_json(raw)
        assert result == {"reply": "hello"}

    def test_whitespace_only_raises(self):
        """Whitespace-only string → ValueError."""
        with pytest.raises(ValueError, match="empty LLM response"):
            extract_json("   \n  \t  ")


# ── normalize_payload ────────────────────────────────────────────────────

class TestNormalizePayload:
    """normalize_payload: coerce LLM dict into the contract shape."""

    def test_full_payload(self):
        """All fields present → normalized correctly."""
        raw = {
            "reply": "Hello!",
            "translation": "你好！",
            "grammar": {
                "is_correct": False,
                "corrected_text": "Hello!",
                "explanation": "Missing exclamation.",
            },
        }
        result = normalize_payload(raw)
        assert result["reply"] == "Hello!"
        assert result["translation"] == "你好！"
        assert result["grammar"]["is_correct"] is False
        assert result["grammar"]["corrected_text"] == "Hello!"
        assert result["grammar"]["explanation"] == "Missing exclamation."
        assert "vocabulary" not in result

    def test_missing_fields(self):
        """Missing optional fields → sensible defaults."""
        raw = {"reply": "Hi"}
        result = normalize_payload(raw)
        assert result["reply"] == "Hi"
        assert result["translation"] == ""
        assert result["grammar"] is None
        assert set(result.keys()) == {"reply", "translation", "grammar"}

    def test_empty_reply_raises(self):
        """Empty reply string → ValueError."""
        with pytest.raises(ValueError, match="empty reply"):
            normalize_payload({"reply": ""})

    def test_missing_reply_uses_text(self):
        """Missing 'reply' but present 'text' key → uses text as reply."""
        result = normalize_payload({"text": "Hello there", "translation": ""})
        assert result["reply"] == "Hello there"

    def test_missing_reply_and_text_raises(self):
        """Neither 'reply' nor 'text' → ValueError."""
        with pytest.raises(ValueError, match="empty reply"):
            normalize_payload({"translation": ""})

    def test_grammar_dict_handling(self):
        """`grammar` as dict → structured; non-dict → None."""
        good = normalize_payload({"reply": "a", "grammar": {"is_correct": True, "corrected_text": "a", "explanation": "OK"}})
        assert good["grammar"] is not None

        bad = normalize_payload({"reply": "a", "grammar": "not a dict"})
        assert bad["grammar"] is None

    def test_reply_stripped(self):
        """Reply string gets stripped."""
        result = normalize_payload({"reply": "  Hello world!  "})
        assert result["reply"] == "Hello world!"

    def test_numeric_reply_converted_to_string(self):
        """Non-string reply values (e.g. int) are converted to string."""
        result = normalize_payload({"reply": 42})
        assert result["reply"] == "42"

    def test_none_reply_raises(self):
        """None reply → ValueError."""
        with pytest.raises(ValueError, match="empty reply"):
            normalize_payload({"reply": None})


# ── fallback_payload ─────────────────────────────────────────────────────

class TestFallbackPayload:
    """fallback_payload: localized canned apology."""

    def test_returns_dict_with_reply_key(self):
        """Returns a dict containing a non-empty 'reply' string."""
        result = fallback_payload("en")
        assert isinstance(result, dict)
        assert "reply" in result
        assert isinstance(result["reply"], str)
        assert result["reply"] != ""

    def test_all_expected_keys_present(self):
        """Fallback dict has all standard shape keys."""
        result = fallback_payload("en")
        assert set(result.keys()) == {"reply", "translation", "grammar"}

    def test_translation_empty(self):
        """Translation is empty string in fallback."""
        result = fallback_payload("en")
        assert result["translation"] == ""

    def test_grammar_none(self):
        """Grammar is None in fallback."""
        result = fallback_payload("en")
        assert result["grammar"] is None

    def test_non_english_language(self):
        """Non-English language returns non-empty reply."""
        result = fallback_payload("zh")
        assert "reply" in result
        assert isinstance(result["reply"], str)
        assert result["reply"] != ""


# ── _extract_reply_prefix ────────────────────────────────────────────────

class TestExtractReplyPrefix:
    """_extract_reply_prefix: value-so-far of the top-level 'reply' key."""

    def test_simple_reply_value(self):
        """Standard reply key → extracts value."""
        result = _extract_reply_prefix('{"reply": "hello"}')
        assert result == "hello"

    def test_partial_reply_value(self):
        """Incomplete reply value → extracts partial."""
        result = _extract_reply_prefix('{"reply": "hel')
        assert result == "hel"

    def test_no_reply_key(self):
        """No 'reply' key → empty string."""
        result = _extract_reply_prefix('{"other": "value"}')
        assert result == ""

    def test_empty_buffer(self):
        """Empty string → empty string."""
        result = _extract_reply_prefix("")
        assert result == ""

    def test_escaped_chars_in_reply(self):
        """Escaped characters inside reply value → correctly captured."""
        result = _extract_reply_prefix('{"reply": "hello\\"world"}')
        assert result == 'hello\\"world'

    def test_multiline_reply_value(self):
        """Newline characters inside reply value → captured."""
        result = _extract_reply_prefix('{"reply": "hello\\nworld"}')
        assert result == "hello\\nworld"

    def test_reply_at_start_of_value(self):
        """Reply value starts immediately after colon."""
        result = _extract_reply_prefix('{"reply":"hi"}')
        assert result == "hi"

    def test_only_reply_opening(self):
        """Only the opening quote of reply value → empty string."""
        result = _extract_reply_prefix('{"reply": "')
        assert result == ""

    def test_nested_reply_object_matches_first(self):
        """Nested reply key found first (regex limitation, not a JSON parser)."""
        result = _extract_reply_prefix('{"data": {"reply": "nested"}, "reply": "top"}')
        # The simple regex matches the first "reply" it finds, which is the nested one.
        # This is a known limitation of the regex approach — it's designed for
        # streaming partial JSON, not full structured objects.
        assert result == "nested"


# ── _unescape_partial ────────────────────────────────────────────────────

class TestUnescapePartial:
    """_unescape_partial: best-effort unescape of a partial JSON string value."""

    def test_simple_string(self):
        """Plain string (no escapes) → returned as-is."""
        result = _unescape_partial("hello")
        assert result == "hello"

    def test_escaped_quote(self):
        """Escaped quote character → properly unescaped."""
        result = _unescape_partial('hello\\"world')
        assert result == 'hello"world'

    def test_escaped_backslash(self):
        """Double backslash → unescaped to a single backslash."""
        result = _unescape_partial("hello\\\\world")
        assert result == "hello\\world"

    def test_trailing_backslash(self):
        """Trailing lone backslash → stripped, remaining text returned."""
        result = _unescape_partial("hello\\")
        assert result == "hello"

    def test_only_trailing_backslash(self):
        """Only a trailing backslash → empty string."""
        result = _unescape_partial("\\")
        assert result == ""

    def test_multiple_escapes(self):
        """Multiple escape sequences → all unescaped correctly."""
        result = _unescape_partial("hello\\nworld\\ttest")
        assert result == "hello\nworld\ttest"

    def test_unicode_escape(self):
        """Unicode escape sequence → decoded."""
        result = _unescape_partial("hello\\u0041")
        assert result == "helloA"

    def test_empty_string(self):
        """Empty string → empty string."""
        result = _unescape_partial("")
        assert result == ""

    def test_escaped_backslash_and_trailing(self):
        """Escaped backslash followed by regular text."""
        result = _unescape_partial("hello\\\\ntest")
        assert result == "hello\\ntest"


# ── Plain-text salvage + empty-stream retry ─────────────────────────────

class FakeChunk:
    """Minimal OpenAI-chunk stand-in: delta with optional content."""

    def __init__(self, content):
        self.choices = [type("C", (), {"delta": type("D", (), {"content": content})()})()]


async def _fake_stream(*chunks):
    for c in chunks:
        yield c


class TestPlainTextSalvage:
    """When the model ignores the JSON contract and speaks plain text, the
    words are kept as the reply instead of the canned glitch fallback."""

    def test_chat_json_salvages_plain_text(self, monkeypatch):
        from types import SimpleNamespace

        async def fake_create(**kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content="嘩，咁你就有好多機會練習喇！")
            )])
        fake_client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create)
        ))
        monkeypatch.setattr("app.services.llm._get_client", lambda force_new=False: fake_client)

        import asyncio
        result = asyncio.run(_import_chat_json([{"role": "user", "content": "hi"}]))
        assert result["reply"] == "嘩，咁你就有好多機會練習喇！"
        assert result["grammar"] is None

    def test_stream_salvages_plain_text(self, monkeypatch):
        from types import SimpleNamespace

        async def fake_create(**kwargs):
            return _fake_stream(FakeChunk("嘩，"), FakeChunk("咁你就有好多機會練習喇！"))
        fake_client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create)
        ))
        monkeypatch.setattr("app.services.llm._get_client", lambda force_new=False: fake_client)

        import asyncio
        tokens, final = [], None
        async def collect():
            nonlocal final
            async for item in _import_chat_json_stream([{"role": "user", "content": "hi"}]):
                if isinstance(item, str):
                    tokens.append(item)
                else:
                    final = item
        asyncio.run(collect())
        assert "".join(tokens) == "嘩，咁你就有好多機會練習喇！"
        assert final["reply"] == "嘩，咁你就有好多機會練習喇！"
        assert not final.get("__llm_failed")


class TestEmptyStreamRetry:
    """DeepSeek intermittently completes with an empty stream — the retry
    loop must kick in and only then fall back."""

    def test_empty_stream_retries_then_falls_back(self, monkeypatch):
        from types import SimpleNamespace

        calls = {"n": 0}
        async def fake_create(**kwargs):
            calls["n"] += 1
            return _fake_stream()  # empty stream, no chunks
        fake_client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create)
        ))
        monkeypatch.setattr("app.services.llm._get_client", lambda force_new=False: fake_client)

        import asyncio
        items = []
        async def collect():
            async for item in _import_chat_json_stream([{"role": "user", "content": "hi"}]):
                items.append(item)
        asyncio.run(collect())
        assert calls["n"] > 1  # retried, not a single attempt
        final = items[-1]
        assert final.get("__llm_failed") is True


def _import_chat_json(messages):
    from app.services.llm import chat_json
    return chat_json(messages, "yue")


def _import_chat_json_stream(messages):
    from app.services.llm import chat_json_stream
    return chat_json_stream(messages, "yue")


class TestSalvageEnrichmentRemoved:
    """v10 (2026-08-06): the extra salvage-enrichment LLM call was deleted
    with the move to json_object mode — a plain-text salvage is wrapped
    LOCALLY (translation stays "") and exactly one create() call happens."""

    def test_salvage_is_local_wrap_single_call(self, monkeypatch):
        from types import SimpleNamespace

        calls = {"n": 0}

        async def fake_create(**kwargs):
            calls["n"] += 1
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content="Great! 早晨 means good morning.")
            )])
        fake_client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create)
        ))
        monkeypatch.setattr("app.services.llm._get_client", lambda force_new=False: fake_client)

        import asyncio
        result = asyncio.run(_import_chat_json([{"role": "user", "content": "hi"}]))
        assert result["reply"] == "Great! 早晨 means good morning."
        assert result["translation"] == ""  # no enrichment call to recover one
        assert calls["n"] == 1  # exactly one LLM call — no enrichment retry


class TestMarkdownStripped:
    """Replies and translations must not carry markdown (**bold**, bullets)
    — the reply is read aloud by TTS, which would speak the asterisks."""

    def test_json_reply_markdown_stripped(self, monkeypatch):
        from types import SimpleNamespace

        async def fake_create(**kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"reply": "**唔該** is used when someone does something", '
                                                '"translation": "**Thank you**", "grammar": null}')
            )])
        fake_client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create)
        ))
        monkeypatch.setattr("app.services.llm._get_client", lambda force_new=False: fake_client)

        import asyncio
        from app.services.llm import chat_json
        result = asyncio.run(chat_json([{"role": "user", "content": "hi"}], "yue"))
        assert "**" not in result["reply"]
        assert "**" not in result["translation"]

    def test_salvaged_plain_text_markdown_stripped(self, monkeypatch):
        from types import SimpleNamespace

        async def fake_create(**kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content="**Good morning!** How are you?")
            )])
        fake_client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create)
        ))
        monkeypatch.setattr("app.services.llm._get_client", lambda force_new=False: fake_client)

        import asyncio
        from app.services.llm import chat_json
        result = asyncio.run(chat_json([{"role": "user", "content": "hi"}], "yue"))
        assert result["reply"] == "Good morning! How are you?"


class TestInvalidJsonNotSalvaged:
    """Invalid JSON-looking output (e.g. unescaped quotes inside the reply:
    '{"reply": "He said "hello" to me"}') must NOT be salvaged as the reply —
    the UI would show raw '{ "reply": ... }' braces and TTS would read them.
    Retry (tenacity), then fall back to the glitch message."""

    def test_json_attempt_retries_then_falls_back(self, monkeypatch):
        from types import SimpleNamespace

        invalid = '{"reply": "He said "hello" to me", "translation": ""}'
        calls = {"n": 0}

        async def fake_create(**kwargs):
            calls["n"] += 1
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=invalid)
            )])

        fake_client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create)
        ))
        monkeypatch.setattr("app.services.llm._get_client", lambda force_new=False: fake_client)

        import asyncio
        from app.services.llm import chat_json
        result = asyncio.run(chat_json([{"role": "user", "content": "hi"}], "yue"))
        assert calls["n"] >= 2  # retried, not a single attempt
        assert "reply" not in result["reply"]  # raw JSON never becomes the reply
        assert not result["reply"].lstrip().startswith("{")


# ── v10 (2026-08-06): DeepSeek v4 request parameters ────────────────────

class TestV4RequestParams:
    """Tutor calls use the real JSON output mode with thinking disabled
    (v4 defaults to thinking ON — latency matters in a voice loop); the
    fast nudge call uses the cheap fast model, also non-thinking."""

    def test_chat_json_sends_json_mode_and_thinking_off(self, monkeypatch):
        from types import SimpleNamespace

        seen = {}

        async def fake_create(**kwargs):
            seen.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"reply": "hi", "translation": "", "grammar": null}')
            )])
        fake_client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create)
        ))
        monkeypatch.setattr("app.services.llm._get_client", lambda force_new=False: fake_client)

        import asyncio
        from app.services.llm import chat_json
        asyncio.run(chat_json([{"role": "user", "content": "hi"}], "yue"))
        assert seen["response_format"] == {"type": "json_object"}
        assert seen["extra_body"] == {"thinking": {"type": "disabled"}}
        assert seen["model"] == "deepseek-v4-pro"

    def test_stream_sends_json_mode_and_thinking_off(self, monkeypatch):
        from types import SimpleNamespace

        seen = {}

        async def fake_create(**kwargs):
            seen.update(kwargs)
            return _fake_stream(FakeChunk('{"reply": "hi", "translation": "", "grammar": null}'))
        fake_client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create)
        ))
        monkeypatch.setattr("app.services.llm._get_client", lambda force_new=False: fake_client)

        import asyncio
        async def collect():
            async for _ in _import_chat_json_stream([{"role": "user", "content": "hi"}]):
                pass
        asyncio.run(collect())
        assert seen["stream"] is True
        assert seen["response_format"] == {"type": "json_object"}
        assert seen["extra_body"] == {"thinking": {"type": "disabled"}}

    def test_fast_reply_uses_fast_model_thinking_off(self, monkeypatch):
        from types import SimpleNamespace

        seen = {}

        async def fake_create(**kwargs):
            seen.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content="regenerated reply")
            )])
        fake_client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create)
        ))
        monkeypatch.setattr("app.services.llm._get_client", lambda force_new=False: fake_client)

        import asyncio
        from app.services.llm import chat_reply_fast
        result = asyncio.run(chat_reply_fast([{"role": "user", "content": "hi"}]))
        assert result == "regenerated reply"
        assert seen["model"] == "deepseek-v4-flash"
        assert seen["extra_body"] == {"thinking": {"type": "disabled"}}
        assert "response_format" not in seen  # plain-text reply by design
