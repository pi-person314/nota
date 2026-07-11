"""Tests for server-side conversation history reconstruction: the last 12
CommandLog rows for a score become alternating user/assistant turns fed
back to Claude on the next command (`nota.orchestrator.loop._load_history`).
"""

from __future__ import annotations

from nota.orchestrator import loop

from .fakes import fake_response, text_block


def test_load_history_is_empty_for_a_fresh_score(make_score):
    score_id = make_score()
    assert loop._load_history(score_id) == []


def test_load_history_alternates_user_and_assistant_turns(make_score):
    score_id = make_score()
    loop._log_command(score_id, "add forte at measure one", ["add_dynamic"], "Added forte at measure 1.")
    loop._log_command(score_id, "undo", ["undo"], "Undid that.")

    history = loop._load_history(score_id)

    assert history == [
        {"role": "user", "content": "add forte at measure one"},
        {"role": "assistant", "content": "Added forte at measure 1."},
        {"role": "user", "content": "undo"},
        {"role": "assistant", "content": "Undid that."},
    ]


def test_load_history_skips_assistant_turn_when_confirmation_is_empty(make_score):
    score_id = make_score()
    loop._log_command(score_id, "add forte at measure one", ["add_dynamic"], "")

    history = loop._load_history(score_id)

    assert history == [{"role": "user", "content": "add forte at measure one"}]


def test_load_history_only_keeps_the_last_twelve_turns(make_score):
    score_id = make_score()
    for i in range(15):
        loop._log_command(score_id, f"command {i}", ["add_dynamic"], f"confirmation {i}")

    history = loop._load_history(score_id)

    # 12 turns, each contributing a user + assistant entry.
    assert len(history) == 24
    transcripts = [entry["content"] for entry in history if entry["role"] == "user"]
    assert transcripts == [f"command {i}" for i in range(3, 15)]
    # Oldest kept turn first, most recent last.
    assert history[0] == {"role": "user", "content": "command 3"}
    assert history[-1] == {"role": "assistant", "content": "confirmation 14"}


def test_run_command_reconstructs_history_for_the_llm(
    make_score, install_fake_client, install_direct_dispatcher
):
    score_id = make_score()
    install_direct_dispatcher()
    loop._log_command(score_id, "add forte at measure one", ["add_dynamic"], "Added forte at measure 1.")

    fake_client = install_fake_client([fake_response(text_block("Added piano at measure 2."))])

    loop.run_command(score_id, "now add piano at measure two")

    sent_messages = fake_client.messages.calls[0]["messages"]
    assert sent_messages[0] == {"role": "user", "content": "add forte at measure one"}
    assert sent_messages[1] == {"role": "assistant", "content": "Added forte at measure 1."}
    assert sent_messages[2] == {"role": "user", "content": "now add piano at measure two"}
