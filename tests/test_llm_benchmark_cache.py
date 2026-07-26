"""The cache must not answer for an experiment it was not run under."""

from scripts.run_llm_benchmark import _cache_identity


def test_identity_changes_with_the_prompt():
    a = _cache_identity("pathumma", "find the PII", "ผมชื่อ นายสมชาย ใจดี")
    b = _cache_identity("pathumma", "find the PII and the dates", "ผมชื่อ นายสมชาย ใจดี")
    assert a != b


def test_identity_changes_with_the_document():
    a = _cache_identity("pathumma", "find the PII", "ผมชื่อ นายสมชาย ใจดี")
    b = _cache_identity("pathumma", "find the PII", "ผมชื่อ นางสาวมาลี รักดี")
    assert a != b


def test_identity_is_stable_for_the_same_inputs():
    args = ("pathumma", "find the PII", "ผมชื่อ นายสมชาย ใจดี")
    assert _cache_identity(*args) == _cache_identity(*args)
