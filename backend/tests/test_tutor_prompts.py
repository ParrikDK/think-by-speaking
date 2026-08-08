"""Tutor prompt tests: levels, scenario injection, strict JSON contract,
history truncation, and no A1/B2 anywhere."""
import pytest

from app.prompts import get_scenario
from app.prompts.tutor import (
    ERROR_MESSAGES,
    JSON_CONTRACT,
    LANGUAGE_NAMES,
    MAX_HISTORY_MESSAGES,
    SILENCE_MESSAGES,
    VALID_LEVELS,
    build_messages,
    build_system_prompt,
)


class TestBeginnerAdaptive:
    """Spec §3.1-3.2: natural greeting opening + production-ending turns."""

    def test_beginner_init_is_natural_greeting(self):
        prompt = build_system_prompt("zh", "beginner", "en", is_init=True)
        assert "answer in EITHER language" in prompt
        assert "how's your day going" in prompt  # the example greeting shape

    def test_beginner_teaches_one_word_inside_greeting(self):
        prompt = build_system_prompt("zh", "beginner", "en", is_init=True)
        assert "weave ONE simple" in prompt

    def test_beginner_production_question_rule(self):
        prompt = build_system_prompt("zh", "beginner", "en", is_init=False)
        assert "PRODUCTION question" in prompt
        assert "NEVER end with bare single-word repetition" in prompt

    def test_beginner_no_fixed_sequence(self):
        prompt = build_system_prompt("zh", "beginner", "en", is_init=False)
        assert "never a fixed sequence" in prompt

    def test_beginner_acknowledge_first(self):
        prompt = build_system_prompt("zh", "beginner", "en", is_init=False)
        assert "acknowledge what they produced first" in prompt


class TestIntermediateFluentAdaptive:
    """Spec §3.2 + design discussion: consistent-but-gentle grammar
    correction, production-ending turns; RULE and mirroring preserved."""

    def test_intermediate_consistent_grammar(self):
        prompt = build_system_prompt("yue", "intermediate", "en", is_init=False)
        assert "consistently but gently" in prompt
        assert "real error" in prompt

    def test_intermediate_production_question(self):
        prompt = build_system_prompt("yue", "intermediate", "en", is_init=False)
        assert "PRODUCTION question" in prompt

    def test_fluent_production_or_open_question(self):
        prompt = build_system_prompt("fr", "fluent", "en", is_init=False)
        assert "PRODUCTION question or a natural open question" in prompt

    def test_fluent_keeps_flow_first_corrections(self):
        prompt = build_system_prompt("fr", "fluent", "en", is_init=False)
        assert "never let the flow die correcting trivia" in prompt

    def test_init_variants_unchanged(self):
        for code, level in (("yue", "intermediate"), ("fr", "fluent")):
            prompt = build_system_prompt(code, level, "en", is_init=True)
            assert "PRODUCTION question" not in prompt  # init = greeting only


class TestFlowRules:
    """QA-judge findings (2026-08-03): session-language fidelity, no
    language announcements, density cap, learner-led close, production
    closers, no stale echoes, no re-teaching the opening word."""

    def test_flow_rules_in_non_init_personas_only(self):
        for level in VALID_LEVELS:
            prompt = build_system_prompt("zh", level, "en", is_init=False)
            assert "FLOW RULES" in prompt
            init = build_system_prompt("zh", level, "en", is_init=True)
            assert "FLOW RULES" not in init

    def test_session_language_fidelity(self):
        prompt = build_system_prompt("zh", "intermediate", "en", is_init=False)
        assert "never switch varieties" in prompt

    def test_no_language_announcement(self):
        prompt = build_system_prompt("yue", "intermediate", "en", is_init=False)
        assert "Never announce" in prompt

    def test_density_cap(self):
        for level in VALID_LEVELS:
            prompt = build_system_prompt("zh", level, "en", is_init=False)
            assert "at most 1-2 new words per turn" in prompt
            assert "never dump more" in prompt

    def test_closing_question_uses_met_words(self):
        prompt = build_system_prompt("zh", "beginner", "en", is_init=False)
        assert "only use words already met" in prompt

    def test_production_not_merely_comprehension(self):
        prompt = build_system_prompt("zh", "beginner", "en", is_init=False)
        assert "not merely understand one" in prompt

    def test_learner_close_respected(self):
        prompt = build_system_prompt("zh", "intermediate", "en", is_init=False)
        assert "close warmly and drop any pending" in prompt

    def test_no_stale_echo_and_no_reteach(self):
        prompt = build_system_prompt("zh", "beginner", "en", is_init=False)
        assert "never open with a previous" in prompt
        assert "never re-teach it from scratch" in prompt


class TestCasualHKRegister:
    """User-directed 2026-08-03 (ported from v8B): casual spoken HK
    Cantonese — 廣東話, never 粵語; HK slang and particles."""

    def test_yue_uses_gwongdungwa_not_jyutjyu(self):
        for level in VALID_LEVELS:
            for is_init in (True, False):
                prompt = build_system_prompt("yue", level, "en", is_init=is_init)
                assert "廣東話" in prompt
                assert "casual" in prompt.lower()

    def test_register_note_scoped_to_yue(self):
        for code in ("zh", "zh-TW", "en", "fr"):
            prompt = build_system_prompt(code, "intermediate", "en")
            assert "廣東話" not in prompt


class TestSharedAdaptationRules:
    """Spec §3.2-3.5: flexible adaptation principle (all personas),
    pronunciation coaching + scenario engine (non-init only)."""

    def test_adaptation_principle_in_all_personas(self):
        for level in VALID_LEVELS:
            for is_init in (True, False):
                prompt = build_system_prompt("yue", level, "en", is_init=is_init)
                assert "an attempt is enthusiasm, not evidence" in prompt
                assert "no assumptions locked in" in prompt

    def test_pronunciation_coach_in_non_init_personas_only(self):
        for level in VALID_LEVELS:
            prompt = build_system_prompt("yue", level, "en", is_init=False)
            assert "was heard, not what was meant" in prompt
            assert "[Typed]" in prompt  # typed messages carry no signal
            init = build_system_prompt("yue", level, "en", is_init=True)
            assert "was heard, not what was meant" not in init

    def test_pronunciation_coach_forbids_fabricated_praise(self):
        prompt = build_system_prompt("yue", "intermediate", "en", is_init=False)
        assert "your pronunciation sounds great" in prompt  # named as forbidden

    def test_scenario_engine_in_non_init_personas_only(self):
        for level in VALID_LEVELS:
            prompt = build_system_prompt("yue", level, "en", is_init=False)
            assert "suggesting real-life situations" in prompt
            init = build_system_prompt("yue", level, "en", is_init=True)
            assert "suggesting real-life situations" not in init


def test_levels_exact():
    assert VALID_LEVELS == ("beginner", "intermediate", "fluent")


@pytest.mark.parametrize("level", VALID_LEVELS)
def test_valid_levels_build(level):
    prompt = build_system_prompt("fr", level)
    assert "French" in prompt


@pytest.mark.parametrize("bad", ["A1", "B2", "C1", "advanced", "", "A2"])
def test_invalid_levels_raise(bad):
    with pytest.raises(ValueError):
        build_system_prompt("fr", bad)


def test_json_contract_instruction_present():
    prompt = build_system_prompt("zh", "beginner")
    for key in ('"reply"', '"translation"', '"grammar"'):
        assert key in prompt
    assert '"vocabulary"' not in prompt
    assert "JSON" in prompt
    assert "is_correct" in prompt


def test_no_A1_anywhere():
    for level in VALID_LEVELS:
        for is_init in (True, False):
            prompt = build_system_prompt("es", level, is_init=is_init)
            assert "A1" not in prompt and "B2" not in prompt and "CEFR" not in prompt


def test_scenario_injection():
    scenario = get_scenario("restaurant")
    prompt = build_system_prompt("zh", "intermediate", scenario_id="restaurant")
    assert scenario["prompt"].strip() in prompt
    # without a scenario, no scenario block
    plain = build_system_prompt("zh", "intermediate")
    assert scenario["prompt"].strip() not in plain


class TestTypedPrefix:
    """Typed Chinese/Cantonese input is marked [Typed]: so the persona can
    tell typed text (no pronunciation signal) from speech (coachable)."""

    def test_typed_prefix_for_chinese(self):
        messages = build_messages("zh", "beginner", [], "你好")
        assert messages[-1]["content"] == "[Typed]: 你好"

    def test_typed_prefix_for_cantonese_and_taiwan(self):
        for code in ("yue", "zh-TW"):
            messages = build_messages(code, "beginner", [], "早晨")
            assert messages[-1]["content"] == "[Typed]: 早晨"

    def test_no_prefix_for_english_or_other_scripts(self):
        assert build_messages("zh", "beginner", [], "hello")[-1]["content"] == "hello"
        assert build_messages("fr", "beginner", [], "salut")[-1]["content"] == "salut"

    def test_no_prefix_on_init(self):
        messages = build_messages("zh", "beginner", [], "", is_init=True)
        assert len(messages) == 1  # no user turn at all


def test_history_truncated_to_20():
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i}"}
        for i in range(30)
    ]
    messages = build_messages("en", "fluent", history, "hello")
    # system + 20 history + new user message
    assert messages[0]["role"] == "system"
    body = messages[1:]
    assert len(body) == MAX_HISTORY_MESSAGES + 1
    assert body[0]["content"] == "msg-10"  # oldest retained
    assert body[-1] == {"role": "user", "content": "hello"}


def test_init_messages_have_no_user_turn():
    messages = build_messages("ja", "beginner", [], "", is_init=True)
    assert len(messages) == 1
    assert messages[0]["role"] == "system"


def test_language_tables():
    # Derived from LANGUAGE_NAMES at runtime — no hardcoded counts
    assert "zh-TW" in LANGUAGE_NAMES
    # Every language with a silence message must have a language name entry
    for lang in SILENCE_MESSAGES:
        assert lang in LANGUAGE_NAMES, f"{lang} has a silence message but is missing from LANGUAGE_NAMES"
    # Silence and error messages should cover the same set of languages
    assert SILENCE_MESSAGES.keys() == ERROR_MESSAGES.keys()


def test_contract_forbids_romanization():
    """The JSON contract still forbids romanization — with the system-side
    justification gone ("the system adds those visually" is now false)."""
    assert "romanization" in JSON_CONTRACT
    assert "NEVER include romanization" in JSON_CONTRACT
    assert "the system adds those visually" not in JSON_CONTRACT


def test_contract_beginner_exception_to_same_language_rule():
    """Review-gate finding 3 (2026-08-03): the contract's same-language
    rule must not fight the beginner persona's 'almost entirely in the
    native language' teaching loop when a beginner attempts the target
    language."""
    assert "Beginner exception" in JSON_CONTRACT
    assert "follow the beginner persona" in JSON_CONTRACT


def test_beginner_persona_has_no_translation_field_hint():
    """The beginner persona no longer tells the LLM to put pronunciation
    hints in the translation field (romanization feature removed)."""
    prompt = build_system_prompt("zh", "beginner", is_init=True)
    assert "Put any pronunciation hints" not in prompt
    assert "never romanization like 'nei5 hou2' or 'ni hao'" in prompt


def test_beginner_teaches_in_native_language():
    """Spec 1 — beginner: converses in the learner's native language,
    introducing target-language words. DeepSeek thinks in the target."""
    for is_init in (True, False):
        prompt = build_system_prompt("zh", "beginner", is_init=is_init, native_language="en")
        assert "Think and reason in Mandarin Chinese" in prompt
        assert "Teach in English:" in prompt


def test_teaching_language_follows_native_selection():
    """The beginner teaching language is the learner's chosen native —
    not hardcoded English."""
    prompt = build_system_prompt("fr", "beginner", native_language="de")
    assert "Teach in German:" in prompt
    assert "Teach in English:" not in prompt


def test_intermediate_greets_in_learning_language():
    """Spec 2 — intermediate init: the tutor speaks the learning language
    with the learner from the first message."""
    prompt = build_system_prompt("yue", "intermediate", is_init=True, native_language="en")
    assert "greet them in Cantonese" in prompt


def test_intermediate_mirrors_learner_language():
    """Spec 2 — intermediate: speaks the learning language when the learner
    does, and answers native-language questions in the native language.
    The language rule is absolute ('RULE ... ENTIRE reply')."""
    for is_init in (True, False):
        prompt = build_system_prompt("yue", "intermediate", is_init=is_init, native_language="en")
        assert "RULE" in prompt
        assert "your ENTIRE reply is in English" in prompt
        assert "Write reply in Cantonese" in prompt or "greet them in Cantonese" in prompt


def test_fluent_still_speaks_target_language():
    """Spec 3 — fluent: full-time learning-language conversation."""
    for is_init in (True, False):
        prompt = build_system_prompt("fr", "fluent", is_init=is_init)
        assert "Write reply in French" in prompt


def test_fluent_authorizes_native_explanation():
    """Spec 3 — fluent: when the learner asks in the native language or for
    an explanation, the tutor's ENTIRE reply is in the native language."""
    for is_init in (True, False):
        prompt = build_system_prompt("fr", "fluent", is_init=is_init, native_language="en")
        assert "your ENTIRE reply is in English" in prompt
        german = build_system_prompt("fr", "fluent", is_init=is_init, native_language="de")
        assert "your ENTIRE reply is in German" in german


def test_contract_forbids_parenthetical_pronunciation_guides():
    """The contract also forbids parenthetical pronunciation guides like
    "好好 (hou2 hou2)" — DeepSeek slipped one in despite the bare-romanization
    rule."""
    assert "(hou2 hou2)" in JSON_CONTRACT
    assert "never add parenthetical" in JSON_CONTRACT


def test_contract_pins_native_language_channel():
    """Translation/grammar must be in the learner's NATIVE language — never
    the target. deepseek-v4-flash drifted these fields to Chinese
    mid-Cantonese conversation despite the plain 'native language' wording,
    so the contract now says it explicitly."""
    assert "NEVER in the target language" in JSON_CONTRACT
    assert "English when the learner's native is English" in JSON_CONTRACT


def test_beginner_translation_is_empty_string():
    """Beginner replies are already written in the native language, so the
    translation field must be an empty string (saves tokens, prevents the
    model drifting the field to the target language)."""
    for is_init in (True, False):
        prompt = build_system_prompt("zh", "beginner", is_init=is_init, native_language="en")
        assert "translation" in prompt
        assert "empty string" in prompt
        # intermediate/fluent still carry translations
        inter = build_system_prompt("zh", "intermediate", is_init=is_init, native_language="en")
        fluent = build_system_prompt("zh", "fluent", is_init=is_init, native_language="en")
        assert "translation field must be an empty string" not in inter
        assert "translation field must be an empty string" not in fluent


# ── v8A QA fix (2026-08-02): translation language must be the native language ──

class TestTranslationLanguageContract:
    """The JSON contract must explicitly forbid drifting the translation to
    any language other than the learner's native one (live-observed:
    simplified-Chinese translation for an English native, 2026-08-02)."""

    def test_contract_forbids_other_translation_languages(self):
        prompt = build_system_prompt("yue", "intermediate", "en")
        assert "NEVER in any other language" in prompt
        assert "the learner's native" in prompt

    def test_contract_explicitly_names_english_for_english_native(self):
        prompt = build_system_prompt("yue", "intermediate", "en")
        assert "English when the learner's native is English" in prompt


# ── v8A QA battery (2026-08-02): contract examples + no-meta-text rule ──

class TestTeachingReplyContract:
    """Teaching replies leak parenthetical romanization and inline meta-text
    ("Translation: ...") — the contract needs explicit examples and a
    no-meta-text rule (the reply is spoken aloud by TTS)."""

    def test_contract_has_bad_romanization_example(self):
        prompt = build_system_prompt("yue", "intermediate", "en")
        assert "BAD example" in prompt
        assert "nei5 hou2" in prompt  # the forbidden example is named

    def test_contract_has_good_example(self):
        prompt = build_system_prompt("yue", "intermediate", "en")
        assert "GOOD example" in prompt

    def test_contract_forbids_inline_translation_meta_text(self):
        prompt = build_system_prompt("yue", "intermediate", "en")
        assert "Translation:" not in prompt  # (the RULE is about the reply content)
        assert "meta" in prompt.lower() or "spoken aloud" in prompt.lower()
