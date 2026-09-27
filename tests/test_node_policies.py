from __future__ import annotations

import pytest
from pydantic import ValidationError

from nodeflowir.ir.node import RetryPolicy, TimeoutPolicy


def test_retry_and_timeout_policies_are_declarative_and_bounded() -> None:
    retry = RetryPolicy(
        max_attempts=3, delay_seconds=1, backoff="exponential", max_delay_seconds=30
    )
    timeout = TimeoutPolicy(timeout_seconds=60)

    assert retry.max_attempts == 3
    assert timeout.timeout_seconds == 60
    with pytest.raises(ValidationError):
        RetryPolicy(max_attempts=2, delay_seconds=10, max_delay_seconds=5)
    with pytest.raises(ValidationError):
        TimeoutPolicy(timeout_seconds=0)
