"""What the core's own session record says, before any client reads it.

The journal is the authoritative copy of a session: a snapshot is built from
it, and a client rebuilt from that snapshot has to end up looking exactly like
one that watched the events arrive. Two properties decide whether that is
true, and both are easy to get subtly wrong:

* the number an item stores is the one its own event was given, not the one
  before it — off by one and a message and the tool after it share a position;
* an unfinished message says it is unfinished — the empty status the journal
  keeps internally must not reach the wire as `completed`.

These run against the journal directly. No service, no provider, no threads
and no sleeps: the sequence is written out, so the assertions are about the
record rather than about timing.
"""

from __future__ import annotations

from comodor.application import Journal

SESSION = {"id": "s1", "mode": "act", "workspace": "/w", "busy": False}


def merged(journal: Journal) -> list[str]:
    """Everything visible, in the one order the core says it happened.

    Messages and tools are numbered in the same domain, so merging on that
    number is what a client does. The sort is stable and keyed on the number
    alone, which is the documented tiebreak: at an equal sequence, messages
    keep their place ahead of tools, and within a list the order they were
    recorded in. A client that sorted on anything else could reorder a
    session the core described unambiguously.
    """
    snapshot = journal.snapshot(SESSION)
    items = (
        [(message["started_seq"], f"message:{message['message_id']}")
         for message in snapshot["messages"]]
        + [(tool["started_seq"], f"tool:{tool['call_id']}")
           for tool in snapshot["tools"]]
    )
    return [name for _, name in sorted(items, key=lambda item: item[0])]


# --------------------------------------------------------------------------- #
# the number an item stores
# --------------------------------------------------------------------------- #

def test_an_item_stores_the_sequence_of_the_event_that_started_it():
    """`started_seq` is the event's own number, not the one before it.

    The journal numbers as it folds, so the value in hand while folding is the
    previous revision. Storing that would date every item one event early — and
    the first item in a session would claim it started at zero, a number no
    event ever carries.
    """
    journal = Journal()

    first = journal.record("message.started",
                           {"message_id": "m1", "turn_id": "t1",
                            "role": "assistant"})
    assert first == 1, "the session's first event is numbered one"

    journal.record("message.delta", {"message_id": "m1", "text": "hi"})
    tool_seq = journal.record("tool.started",
                              {"call_id": "c1", "turn_id": "t1", "name": "grep"})

    snapshot = journal.snapshot(SESSION)
    assert snapshot["messages"][0]["started_seq"] == first
    assert snapshot["tools"][0]["started_seq"] == tool_seq
    assert snapshot["tools"][0]["started_seq"] == 3
    # And the counter moved with them, so the two cannot drift apart.
    assert snapshot["revision"] == 3


def test_numbering_has_no_gaps_and_no_repeats():
    journal = Journal()
    given = [journal.record(name, {"message_id": "m1", "turn_id": "t1"})
             for name in ("message.started", "message.delta",
                          "message.completed")]
    assert given == [1, 2, 3]
    assert journal.revision == 3


def test_reading_a_snapshot_does_not_change_the_record():
    """A snapshot taken mid-answer must not finish the answer."""
    journal = Journal()
    journal.record("message.started",
                   {"message_id": "m1", "turn_id": "t1", "role": "assistant"})
    journal.record("message.delta", {"message_id": "m1", "text": "half"})

    before = journal.snapshot(SESSION)
    after = journal.snapshot(SESSION)

    assert before == after
    assert journal.revision == 2
    assert journal.open_message() is not None


# --------------------------------------------------------------------------- #
# an open message is open
# --------------------------------------------------------------------------- #

def test_an_open_message_says_streaming_rather_than_completed():
    """The wire model has a word for "not finished yet", and uses it.

    Internally an open message has an empty status, because nothing has said
    how it ended. Serialising that as `completed` told a rebuilt client the
    answer was finished, so it stopped listening to a message that was still
    streaming deltas at it.
    """
    journal = Journal()
    journal.record("message.started",
                   {"message_id": "m1", "turn_id": "t1", "role": "assistant"})
    journal.record("message.delta", {"message_id": "m1", "text": "hel"})

    snapshot = journal.snapshot(SESSION)
    message = snapshot["messages"][0]
    assert message["status"] == "streaming"
    assert message["text"] == "hel"

    # And the same message, once it has ended, says how.
    journal.record("message.completed",
                   {"message_id": "m1", "text": "hello", "status": "completed"})
    finished = journal.snapshot(SESSION)["messages"][0]
    assert finished["status"] == "completed"
    assert finished["text"] == "hello"
    assert len(journal.snapshot(SESSION)["messages"]) == 1, "not duplicated"


def test_how_a_message_ended_survives_into_the_snapshot():
    journal = Journal()
    journal.record("message.started",
                   {"message_id": "m1", "turn_id": "t1", "role": "assistant"})
    journal.record("message.completed",
                   {"message_id": "m1", "text": "half an", "status": "cancelled"})

    assert journal.snapshot(SESSION)["messages"][0]["status"] == "cancelled"


# --------------------------------------------------------------------------- #
# one ordering domain
# --------------------------------------------------------------------------- #

def test_messages_and_tools_interleave_the_way_the_turn_did():
    """A X B Y C, not every message followed by every tool.

    A turn is an answer, the tool it called, another answer, another tool and
    a closing answer. Two arrays in a snapshot invite a client to draw them
    one after the other, which puts the closing summary above the work it
    summarises and loses which tool belonged to which part.
    """
    journal = Journal()
    timeline = [
        ("message.started", {"message_id": "A", "turn_id": "t1",
                             "role": "assistant"}),
        ("message.completed", {"message_id": "A", "text": "Looking.",
                               "status": "completed"}),
        ("tool.started", {"call_id": "X", "turn_id": "t1", "name": "read_file"}),
        ("tool.output", {"call_id": "X", "text": "the file\n"}),
        ("tool.completed", {"call_id": "X"}),
        ("message.started", {"message_id": "B", "turn_id": "t1",
                             "role": "assistant"}),
        ("message.completed", {"message_id": "B", "text": "Found it.",
                               "status": "completed"}),
        ("tool.started", {"call_id": "Y", "turn_id": "t1", "name": "edit_file"}),
        ("tool.completed", {"call_id": "Y"}),
        ("message.started", {"message_id": "C", "turn_id": "t1",
                             "role": "assistant"}),
    ]
    for name, params in timeline:
        journal.record(name, params)

    assert merged(journal) == ["message:A", "tool:X", "message:B",
                               "tool:Y", "message:C"]


def test_the_persons_prompt_is_ordered_before_the_answer_to_it():
    """The prompt no event announces still has a place in the timeline."""
    journal = Journal()
    journal.said("t1", "have a look")
    journal.record("message.started",
                   {"message_id": "A", "turn_id": "t1", "role": "assistant"})
    journal.record("tool.started",
                   {"call_id": "X", "turn_id": "t1", "name": "read_file"})

    assert merged(journal) == ["message:user-t1", "message:A", "tool:X"]


def test_several_turns_keep_their_history_in_order():
    journal = Journal()
    for turn in ("t1", "t2"):
        journal.said(turn, f"prompt {turn}")
        journal.record("message.started",
                       {"message_id": f"a-{turn}", "turn_id": turn,
                        "role": "assistant"})
        journal.record("tool.started",
                       {"call_id": f"x-{turn}", "turn_id": turn, "name": "grep"})
        journal.record("tool.completed", {"call_id": f"x-{turn}"})
        journal.record("message.completed",
                       {"message_id": f"a-{turn}", "text": "done",
                        "status": "completed"})

    assert merged(journal) == [
        "message:user-t1", "message:a-t1", "tool:x-t1",
        "message:user-t2", "message:a-t2", "tool:x-t2",
    ]


def test_parallel_tools_keep_their_own_starts():
    """Two tools started in one turn are ordered by when each began."""
    journal = Journal()
    journal.record("tool.started",
                   {"call_id": "A", "turn_id": "t1", "name": "alpha"})
    journal.record("tool.started",
                   {"call_id": "B", "turn_id": "t1", "name": "bravo"})
    journal.record("tool.output", {"call_id": "B", "text": "b1\n"})
    journal.record("tool.output", {"call_id": "A", "text": "a1\n"})

    assert merged(journal) == ["tool:A", "tool:B"]
    snapshot = journal.snapshot(SESSION)
    by_id = {tool["call_id"]: tool for tool in snapshot["tools"]}
    assert by_id["A"]["output"] == "a1\n"
    assert by_id["B"]["output"] == "b1\n"


def test_an_equal_number_keeps_the_prompt_ahead_of_the_answer():
    """The tiebreak, stated rather than left to a sort implementation.

    The prompt is recorded against the number the session is about to use,
    because spending one of its own would leave a hole a client reads as a
    gap. In the real flow an event always lands on that number first, so the
    two never actually tie — but a client must not be able to reorder them if
    they do, so the rule is written down and tested: messages before tools,
    recorded order within a list.
    """
    journal = Journal()
    journal.said("t1", "have a look")
    journal.record("message.started",
                   {"message_id": "A", "turn_id": "t1", "role": "assistant"})
    journal.record("tool.started",
                   {"call_id": "X", "turn_id": "t1", "name": "read_file"})

    snapshot = journal.snapshot(SESSION)
    numbers = [message["started_seq"] for message in snapshot["messages"]]
    assert numbers[0] == numbers[1], "the case under test is a genuine tie"
    assert merged(journal)[0] == "message:user-t1"
