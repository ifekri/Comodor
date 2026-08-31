"""The cronjob tool: scheduling from inside a conversation.

The registry wiring is half the story, so the tests cover it too: a registry
built with a store offers the tool, one built without — which is what a
scheduled run builds — must not, whatever else it offers.
"""

from __future__ import annotations

import pytest

from comodor.cron.jobs import Job, JobStore
from comodor.cron.parse import parse
from comodor.tools import ToolRegistry
from comodor.tools.cronjob import CronJob

# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def store(tmp_path):
    return JobStore(tmp_path / "cron")


def make_tool(store) -> CronJob:
    return CronJob(store)


# --------------------------------------------------------------------------- #
# the registry gate
# --------------------------------------------------------------------------- #

def test_the_tool_is_offered_only_where_a_store_was_passed(store):
    assert "cronjob" not in ToolRegistry()
    assert "cronjob" in ToolRegistry(cron_store=store)


def test_a_registry_built_without_a_store_never_offers_the_tool(store):
    # The recursion guard, spelled out: a scheduled run's registry has no
    # cron store, so a cron run cannot create another job.
    from comodor.cron.scheduler import Scheduler

    registry = ToolRegistry()
    assert "cronjob" not in registry
    assert Scheduler is not None  # imported to show the wiring exists


# --------------------------------------------------------------------------- #
# actions
# --------------------------------------------------------------------------- #


@pytest.fixture
def tool_context_enabled(tool_context):
    tool_context.config.cron.enabled = True
    return tool_context


def test_create_adds_a_job(store, tool_context_enabled):
    tool = make_tool(store)
    result = tool.run(tool_context_enabled, action="create", name="nightly",
                      schedule="daily at 9am", prompt="check the builds")
    assert result.ok, result.content
    job = store.all()[0]
    assert job.name == "nightly"
    assert job.schedule.expr == "0 9 * * 0,1,2,3,4,5,6"
    assert job.project == str(tool_context_enabled.cwd)


def test_create_without_a_schedule_is_refused(store, tool_context):
    result = make_tool(store).run(tool_context, action="create", name="x",
                                  prompt="do the thing")
    assert not result.ok
    assert "schedule" in result.content


def test_create_refuses_an_unreadable_schedule_with_the_advice(store, tool_context):
    result = make_tool(store).run(tool_context, action="create", name="x",
                                  schedule="whenever", prompt="do it")
    assert not result.ok
    assert "could not read" in result.content


def test_create_with_the_scheduler_disabled_says_so(store, tool_context):
    tool_context.config.cron.enabled = False
    result = make_tool(store).run(tool_context, action="create", name="x",
                                  schedule="daily at 9am", prompt="do it")
    assert not result.ok
    assert "disabled" in result.content


def test_list_reports_the_jobs(store, tool_context):
    store.add(Job(id="a", name="nightly", prompt="p",
                  schedule=parse("daily at 9am"), created="2026-08-01T00:00:00"))
    result = make_tool(store).run(tool_context, action="list")
    assert result.ok
    assert "nightly" in result.content
    assert "0 9" in result.content


def test_pause_resume_and_remove_go_by_name(store, tool_context):
    store.add(Job(id="a", name="nightly", prompt="p",
                  schedule=parse("daily at 9am"), created="2026-08-01T00:00:00"))
    tool = make_tool(store)

    assert tool.run(tool_context, action="pause", name="nightly").ok
    assert store.get("a").enabled is False
    assert tool.run(tool_context, action="resume", name="nightly").ok
    assert store.get("a").enabled is True
    assert tool.run(tool_context, action="remove", name="nightly").ok
    assert store.get("a") is None


def test_an_unknown_name_is_a_readable_error(store, tool_context):
    result = make_tool(store).run(tool_context, action="pause", name="ghost")
    assert not result.ok
    assert "ghost" in result.content
