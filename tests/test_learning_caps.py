"""At-cap behaviour: refuse and list, never evict (T117; FR-065).

The caps are unchanged by this feature — 8 project facts, 6 user facts. When
one is full, adding produces an explicit refusal naming the current contents,
and nothing already stored is removed to make room.
"""

from __future__ import annotations

import pytest

from comodor.learning import BrainStore
from comodor.learning.facts import MEMORY_CAP, USER_CAP, FactError, FactService


@pytest.fixture
def service(tmp_path):
    store = BrainStore(tmp_path / "brain.db", async_writes=False)
    yield FactService(store, scopes=["global", "project:p"], write_scope="project:p")
    store.close()


def test_the_caps_are_the_documented_ones():
    assert (MEMORY_CAP, USER_CAP) == (8, 6)


def test_the_project_cap_refuses_and_lists(service):
    for index in range(MEMORY_CAP):
        service.add(f"project fact number {index}", provenance="user_statement")
    before = [fact.id for fact in service.entries("memory")]
    assert len(before) == MEMORY_CAP

    with pytest.raises(FactError) as refusal:
        service.add("one fact too many", provenance="user_statement")
    message = str(refusal.value)
    assert "Current entries" in message
    for fact_id in before:
        assert f"#{fact_id}" in message
    assert [fact.id for fact in service.entries("memory")] == before, "nothing evicted"


def test_the_user_cap_refuses_and_lists(service):
    for index in range(USER_CAP):
        service.add(f"user preference {index}", kind="user", provenance="user_statement")
    before = [fact.id for fact in service.entries("user")]

    with pytest.raises(FactError) as refusal:
        service.add("one preference too many", kind="user", provenance="user_statement")
    assert "Current entries" in str(refusal.value)
    assert [fact.id for fact in service.entries("user")] == before


def test_an_exact_duplicate_is_not_a_cap_violation(service):
    for index in range(MEMORY_CAP):
        service.add(f"project fact number {index}", provenance="user_statement")
    existing = service.entries("memory")[0]
    again = service.add(existing.text, provenance="user_statement")
    assert again.id == existing.id
    assert len(service.entries("memory")) == MEMORY_CAP


def test_mutation_with_an_evicting_gate_the_fact_would_be_lost(service):
    """The gate refuses; it does not make room. Demonstrated by contrast: the
    count after a refused add equals the count before."""
    for index in range(MEMORY_CAP):
        service.add(f"project fact number {index}", provenance="user_statement")
    with pytest.raises(FactError):
        service.add("overflow", provenance="user_statement")
    assert len(service.entries("memory")) == MEMORY_CAP
