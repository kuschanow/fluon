"""Reusable test suites for fluon extension points. Requires pytest (``pip install fluon[testing]``)."""

import pytest

# Contract tests live in the package, not in a test file: without this pytest would not rewrite their asserts.
pytest.register_assert_rewrite("fluon.testing.backend_contract")

from fluon.testing.backend_contract import BackendContract  # noqa: E402

__all__ = ["BackendContract"]
