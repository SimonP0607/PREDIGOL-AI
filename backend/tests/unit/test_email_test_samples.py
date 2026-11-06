"""The operator's QA mailbox (closing plan 4.1): one sample of every e-mail a reader can receive, with moments that are
still ahead when it is sent - a sample written with a date in the past would be dropped by the queue as «too late»."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scripts import email_test

from fbi.messaging.templates import COMMERCIAL, TEMPLATES, check_params

AT = datetime(2026, 11, 5, 17, 40, 12, tzinfo=UTC)


def test_the_qa_mailbox_holds_every_email_that_can_be_a_sample() -> None:
    names = {t.name for t in email_test.samples()}
    assert names == {n for n, t in TEMPLATES.items() if t.grant is None and t.category not in COMMERCIAL}
    assert {"welcome", "trial_started", "payment_recorded", "maintenance_scheduled", "incident_resolved",
            "important_change"} <= names
    assert "activation_reminder" not in names and "invitation" not in names, "a link belongs to one token"
    assert "weekly_digest" not in names, "commercial mail needs the reader's consent"


def test_a_sample_keeps_its_shape_and_its_moments_are_ahead_of_now() -> None:
    for template in email_test.samples():
        params = email_test.current_sample(template, AT)
        check_params(template.name, params)  # the queue would accept it
        for key, value in params.items():
            if key in {"starts", "ends", "resolved"}:
                assert datetime.fromisoformat(value) >= AT, f"{template.name}.{key} is in the past"


def test_a_maintenance_keeps_its_length_and_the_earliest_moment_is_a_day_ahead() -> None:
    params = email_test.current_sample(TEMPLATES["maintenance_scheduled"], AT)
    starts, ends = datetime.fromisoformat(params["starts"]), datetime.fromisoformat(params["ends"])
    assert starts == datetime(2026, 11, 6, 17, 0, tzinfo=UTC)
    assert ends - starts == timedelta(hours=1)


def test_a_sample_without_moments_is_the_sample_itself() -> None:
    template = TEMPLATES["important_change"]
    assert email_test.current_sample(template, AT) == dict(template.sample)
