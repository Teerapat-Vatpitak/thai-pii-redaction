"""The cache must not answer for an experiment it was not run under."""

from copy import deepcopy

from benchmark.llm_providers import provider_request_config
from scripts.run_llm_benchmark import _cache_identity


def test_identity_changes_with_the_prompt():
    config = provider_request_config("pathumma")
    a = _cache_identity(config, "find the PII", "ผมชื่อ นายสมชาย ใจดี")
    b = _cache_identity(config, "find the PII and the dates", "ผมชื่อ นายสมชาย ใจดี")
    assert a != b


def test_identity_changes_with_the_document():
    config = provider_request_config("pathumma")
    a = _cache_identity(config, "find the PII", "ผมชื่อ นายสมชาย ใจดี")
    b = _cache_identity(config, "find the PII", "ผมชื่อ นางสาวมาลี รักดี")
    assert a != b


def test_identity_is_stable_for_the_same_inputs():
    args = (provider_request_config("pathumma"), "find the PII", "ผมชื่อ นายสมชาย ใจดี")
    assert _cache_identity(*args) == _cache_identity(*args)


def test_identity_changes_with_model_or_generation_config():
    config = provider_request_config("tokenmind")
    changed_model = {**config, "model": "another-model"}
    changed_thinking = deepcopy(config)
    changed_thinking["extra_body"]["chat_template_kwargs"]["enable_thinking"] = True

    base = _cache_identity(config, "find the PII", "text")

    assert _cache_identity(changed_model, "find the PII", "text") != base
    assert _cache_identity(changed_thinking, "find the PII", "text") != base
