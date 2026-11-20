"""Reproducible profiles shared by source and installed-wheel tests."""

import os

from hypothesis import HealthCheck, settings

settings.register_profile(
    "language-pr", max_examples=200, derandomize=True, deadline=None, print_blob=True
)
settings.register_profile(
    "language-deep",
    max_examples=2000,
    derandomize=True,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("TRADELANG_TEST_PROFILE", "language-pr"))
