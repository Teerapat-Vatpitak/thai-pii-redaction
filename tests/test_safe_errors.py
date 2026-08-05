"""Adversarial tests for sensitive exception-graph disposal."""

import subprocess
import sys

from pii_redactor.safe_errors import discard_exception_graph


class HostileException(RuntimeError):
    """Reject normal attribute access to exercise the built-in bypass."""

    def __getattribute__(self, name):
        if name in {"__traceback__", "__cause__", "__context__"}:
            raise RuntimeError("hostile attribute read")
        return super().__getattribute__(name)

    def __setattr__(self, name, value):
        if name in {"__traceback__", "__cause__", "__context__"}:
            raise RuntimeError("hostile attribute write")
        return super().__setattr__(name, value)


def _raise_retained(error):
    sensitive_local = "synthetic-sensitive-local"
    assert sensitive_local
    raise error


def test_discard_bypasses_hostile_exception_attribute_overrides():
    retained = HostileException("synthetic")
    try:
        _raise_retained(retained)
    except HostileException as error:
        discard_exception_graph(error)

    assert BaseException.__getattribute__(retained, "__traceback__") is None
    assert BaseException.__getattribute__(retained, "__cause__") is None
    assert BaseException.__getattribute__(retained, "__context__") is None


def test_discard_clears_exception_group_members():
    first = RuntimeError("first")
    second = ValueError("second")
    for retained in (first, second):
        try:
            _raise_retained(retained)
        except Exception:
            pass
    group = ExceptionGroup("provider failures", [first, second])

    discard_exception_graph(group)

    assert group.__traceback__ is None
    assert group.message == "provider failures"
    assert repr(group)
    for retained in (first, second):
        assert retained.__traceback__ is None
        assert retained.__cause__ is None
        assert retained.__context__ is None
        assert retained.args == ()


def test_discard_keeps_exception_group_repr_valid_in_subprocess():
    code = """
from pii_redactor.safe_errors import discard_exception_graph
member = ValueError("SYNTHETIC_CHILD_PRIVATE_VALUE")
group = ExceptionGroup("SYNTHETIC_GROUP_PRIVATE_VALUE", [member])
discard_exception_graph(group)
repr(group)
assert group.message == "SYNTHETIC_GROUP_PRIVATE_VALUE"
assert member.args == ()
print("safe")
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "safe"
    assert completed.stderr == ""


def test_discard_clears_custom_and_unicode_exception_payloads():
    private_marker = "SYNTHETIC_PRIVATE_RENDER_VALUE"
    retained = UnicodeEncodeError(
        "utf-8",
        f"{private_marker}\ud800",
        len(private_marker),
        len(private_marker) + 1,
        private_marker,
    )
    retained.provider_body = private_marker
    retained.mapping = {"token": private_marker}

    discard_exception_graph(retained)

    assert retained.args == ()
    assert retained.object == ""
    assert retained.reason == "encoding failed"
    assert retained.__dict__ == {}
    assert private_marker not in repr(retained)
