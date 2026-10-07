from assistant.scheduler import parse_schedule_args


def test_parse_duration_minutes() -> None:
    parsed = parse_schedule_args(["30m", "Revisar logs"])
    assert parsed is not None
    run_at, desc = parsed
    assert desc == "Revisar logs"
    assert run_at.tzinfo is not None


def test_parse_iso_datetime() -> None:
    parsed = parse_schedule_args(["2026-10-08T10:00", "Reunión"])
    assert parsed is not None
    run_at, desc = parsed
    assert desc == "Reunión"
    assert run_at.hour == 10
