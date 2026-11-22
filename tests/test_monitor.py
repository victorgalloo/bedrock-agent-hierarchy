from agent_hierarchy.monitor import AreaSnapshot, should_wake


def test_wakes_only_on_change() -> None:
    quiet = AreaSnapshot(iso_week="2026-W03", open_exceptions=frozenset({"e1"}))
    assert should_wake(None, quiet).wake
    assert not should_wake(quiet, quiet).wake
    assert should_wake(quiet, AreaSnapshot("2026-W03", frozenset({"e1", "e2"}))).wake
    assert should_wake(quiet, AreaSnapshot("2026-W04", frozenset({"e1"}))).wake
    assert should_wake(quiet, AreaSnapshot("2026-W03", frozenset({"e1"}), 1)).wake
