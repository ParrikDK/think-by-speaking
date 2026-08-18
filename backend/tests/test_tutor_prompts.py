"""Debate-coach prompt tests: levels, subject injection, strict JSON
contract (feedback card), depth tiers, debate ethics, learner profile
injection, history truncation, and no A1/B2 anywhere.

v13 rewrite (2026-08-18): the app converted from a language tutor to a
general debate coach ("just so that I think by speaking").
"""
import json

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


# ── Levels ─────────────────────────────────────────────────────────

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


def test_no_A1_anywhere():
    for level in VALID_LEVELS:
        for is_init in (True, False):
            prompt = build_system_prompt("es", level, is_init=is_init)
            assert "A1" not in prompt and "B2" not in prompt and "CEFR" not in prompt


# ── Debate depth tiers ─────────────────────────────────────────────

class TestDebateDepths:
    """v13: level maps to debate depth — Basics / Balanced / Expert."""

    def test_beginner_is_basics_depth(self):
        prompt = build_system_prompt("en", "beginner", is_init=False)
        assert "BASICS depth" in prompt
        assert "no jargon" in prompt

    def test_intermediate_is_balanced_depth(self):
        prompt = build_system_prompt("en", "intermediate", is_init=False)
        assert "BALANCED depth" in prompt
        assert "plain reasoning" in prompt or "one idea per turn" in prompt

    def test_fluent_is_expert_depth(self):
        prompt = build_system_prompt("en", "fluent", is_init=False)
        assert "EXPERT depth" in prompt
        assert "steelman" in prompt

    def test_beginner_init_asks_what_they_believe(self):
        prompt = build_system_prompt("en", "beginner", is_init=True)
        assert "what they currently believe" in prompt
        assert "no jargon" in prompt

    def test_greetings_state_the_stance(self):
        for level in VALID_LEVELS:
            prompt = build_system_prompt("en", level, is_init=True)
            assert "state the subject" in prompt or "state the subject's" in prompt
            assert (
                "invite their first claim" in prompt
                or "invite the learner's first claim" in prompt
                or "ask the learner what they currently believe" in prompt
            )

    def test_concede_when_right(self):
        for level in ("intermediate", "fluent"):
            prompt = build_system_prompt("en", level, is_init=False)
            assert "concede when" in prompt and "right" in prompt

    def test_init_variants_teach_nothing(self):
        for level in VALID_LEVELS:
            prompt = build_system_prompt("en", level, is_init=True)
            assert "FLOW RULES" not in prompt
            assert "SUBJECT STEERING" not in prompt


# ── Language rules ─────────────────────────────────────────────────

class TestLanguageRules:
    """The debate happens in the session's debate language; the RULE mirror
    (entire reply in the native language) is preserved from v12."""

    def test_entire_reply_rule_in_native(self):
        for level in VALID_LEVELS:
            prompt = build_system_prompt("yue", level, is_init=False, native_language="en")
            assert "RULE" in prompt
            assert "your ENTIRE reply is in English" in prompt

    def test_write_reply_in_debate_language(self):
        prompt = build_system_prompt("fr", "fluent", is_init=False)
        assert "debating in French" in prompt or "debate in French" in prompt
        assert "debate coach" in prompt

    def test_flow_rules_in_non_init_only(self):
        for level in VALID_LEVELS:
            prompt = build_system_prompt("zh", level, is_init=False)
            assert "FLOW RULES" in prompt
            init = build_system_prompt("zh", level, is_init=True)
            assert "FLOW RULES" not in init

    def test_no_language_announcement(self):
        prompt = build_system_prompt("yue", "intermediate", is_init=False)
        assert "Never announce" in prompt

    def test_one_idea_per_turn(self):
        for level in VALID_LEVELS:
            prompt = build_system_prompt("zh", level, is_init=False)
            assert "at most one new idea per turn" in prompt

    def test_closer_forces_production(self):
        for level in VALID_LEVELS:
            prompt = build_system_prompt("zh", level, is_init=False)
            assert "forces the learner to PRODUCE an argument" in prompt

    def test_warm_close_with_final_score(self):
        prompt = build_system_prompt("zh", "intermediate", is_init=False)
        assert "close warmly, give the final score" in prompt

    def test_open_by_naming_latest_claim(self):
        prompt = build_system_prompt("zh", "beginner", is_init=False)
        assert "naming the learner's latest claim" in prompt
        assert "never open with a stale point" in prompt


# ── Subject injection ──────────────────────────────────────────────

def test_subject_injection():
    scenario = get_scenario("ai-future")
    prompt = build_system_prompt("en", "intermediate", scenario_id="ai-future")
    assert "SUBJECT — debate this claim:" in prompt
    assert scenario["prompt"].strip() in prompt
    # without a subject, no subject block
    plain = build_system_prompt("en", "intermediate")
    assert "SUBJECT — debate this claim:" not in plain


def test_unknown_subject_ignored():
    prompt = build_system_prompt("en", "intermediate", scenario_id="nope")
    assert "SUBJECT — debate this claim:" not in prompt


class TestSubjectSteering:
    def test_subject_steering_in_non_init_only(self):
        for level in VALID_LEVELS:
            prompt = build_system_prompt("yue", level, is_init=False)
            assert "SUBJECT STEERING" in prompt
            assert "offer a fresh angle" in prompt
            init = build_system_prompt("yue", level, is_init=True)
            assert "SUBJECT STEERING" not in init


# ── Adaptation + debate ethics ─────────────────────────────────────

class TestSharedRules:
    def test_adaptation_principle_in_all_personas(self):
        for level in VALID_LEVELS:
            for is_init in (True, False):
                prompt = build_system_prompt("yue", level, is_init=is_init)
                assert "ADAPTATION PRINCIPLE" in prompt
                assert "clarify-then-challenge" in prompt

    def test_debate_ethics_in_all_personas(self):
        for level in VALID_LEVELS:
            for is_init in (True, False):
                prompt = build_system_prompt("yue", level, is_init=is_init)
                assert "DEBATE ETHICS" in prompt
                assert "argue ideas, never the person" in prompt
                assert "steelman" in prompt

    def test_no_pronunciation_coach_anywhere(self):
        for level in VALID_LEVELS:
            for is_init in (True, False):
                prompt = build_system_prompt("yue", level, is_init=is_init)
                assert "PRONUNCIATION" not in prompt
                assert "was heard, not what was meant" not in prompt


# ── JSON contract (feedback card) ──────────────────────────────────

def test_json_contract_instruction_present():
    prompt = build_system_prompt("zh", "beginner")
    for key in ('"reply"', '"translation"', '"feedback"'):
        assert key in prompt
    assert '"grammar"' not in prompt  # v13: grammar object removed
    assert "JSON" in prompt
    assert '"stance"' in prompt
    assert '"score"' in prompt
    assert '"score_delta"' in prompt


def test_contract_feedback_null_only_on_greeting():
    assert "feedback is null ONLY on the very first greeting message" in JSON_CONTRACT


def test_contract_score_rules():
    assert "start at 50" in JSON_CONTRACT
    assert "±8" in JSON_CONTRACT
    assert "clamp 0-100" in JSON_CONTRACT


def test_contract_screen_fields_in_native():
    assert "counter, evidence and next are read on screen, never spoken" in JSON_CONTRACT
    assert "learner's native language" in JSON_CONTRACT


def test_contract_forbids_romanization():
    assert "never romanization" in JSON_CONTRACT
    assert "meta-words" in JSON_CONTRACT


def test_contract_empty_translation_rule():
    assert "empty string when the reply is already written in the learner's native language" in JSON_CONTRACT


# ── Learner profile injection (v13 — the personalization moat) ─────

def test_profile_injected_when_given():
    profile = {"interests": ["tech"], "style": "devils_advocate"}
    prompt = build_system_prompt("en", "intermediate", profile=profile)
    assert "LEARNER PROFILE" in prompt
    assert '"interests"' in prompt
    assert "tech" in prompt
    assert "never mention the profile in the reply" in prompt


def test_profile_absent_when_not_given():
    prompt = build_system_prompt("en", "intermediate")
    assert "LEARNER PROFILE" not in prompt


def test_profile_injected_on_init_too():
    prompt = build_system_prompt("en", "beginner", is_init=True, profile={"interests": ["sports"]})
    assert "LEARNER PROFILE" in prompt


def test_profile_flows_through_build_messages():
    messages = build_messages(
        "en", "intermediate", [], "hello",
        profile={"interests": ["money"]},
    )
    assert "LEARNER PROFILE" in messages[0]["content"]
    assert "money" in messages[0]["content"]


# ── HK register (kept from the language era — variety pinning) ─────

class TestCasualHKRegister:
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


# ── Typed prefix (kept — harmless historical marker) ───────────────

class TestTypedPrefix:
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


# ── History ────────────────────────────────────────────────────────

def test_history_truncated_to_20():
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i}"}
        for i in range(30)
    ]
    messages = build_messages("en", "fluent", history, "hello")
    assert messages[0]["role"] == "system"
    body = messages[1:]
    assert len(body) == MAX_HISTORY_MESSAGES + 1
    assert body[0]["content"] == "msg-10"  # oldest retained
    assert body[-1] == {"role": "user", "content": "hello"}


def test_init_messages_have_no_user_turn():
    messages = build_messages("ja", "beginner", [], "", is_init=True)
    assert len(messages) == 1
    assert messages[0]["role"] == "system"


# ── Language tables ────────────────────────────────────────────────

def test_language_tables():
    assert "zh-TW" in LANGUAGE_NAMES
    for lang in SILENCE_MESSAGES:
        assert lang in LANGUAGE_NAMES, f"{lang} has a silence message but is missing from LANGUAGE_NAMES"
    assert SILENCE_MESSAGES.keys() == ERROR_MESSAGES.keys()
