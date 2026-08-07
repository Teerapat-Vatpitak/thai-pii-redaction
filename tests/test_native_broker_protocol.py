from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import native_broker_protocol as protocol

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "native_broker" / "v1" / "conformance.json"
CONTRACT_PATH = ROOT / "native-broker" / "protocol-v1.json"
FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CONTRACT_FILE = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _bytes(vector: dict[str, object]) -> bytes:
    return str(vector["json"]).encode("utf-8")


def _state(
    role: str,
    *,
    hello_request_id: str | None = None,
) -> protocol.ConnectionState:
    hello = protocol.canonical_json_bytes(
        {
            "claimed_role": role,
            "client_product_version": "9.9.9-test",
            "request_id": hello_request_id or f"hello-{role}",
            "supported_protocol_versions": [1],
        }
    )
    state = protocol.negotiate_hello(
        hello,
        authenticated_role=role,
        broker_product_version="8.8.8-test",
    ).state
    return state


def test_machine_contract_is_the_single_loaded_policy_truth():
    assert FIXTURES["fixture_schema_version"] == 1
    assert protocol.CONTRACT_PATH.resolve() == CONTRACT_PATH.resolve()
    assert protocol.CONTRACT == CONTRACT_FILE
    assert protocol.CONTRACT["contract_schema_version"] == 1
    assert protocol.CONTRACT["supported_protocol_versions"] == [1]
    assert set(protocol.CONTRACT["errors"]) == {
        vector["code"] for vector in FIXTURES["error_messages"]
    }
    assert "backend" not in protocol.CONTRACT["roles"]
    for operations in protocol.CONTRACT["roles"].values():
        assert set(operations) <= set(protocol.CONTRACT["operations"])


@pytest.mark.parametrize(
    "vector",
    [item for item in FIXTURES["hello_vectors"] if "expect_error" not in item],
    ids=lambda item: item["name"],
)
def test_valid_hello_and_highest_common_negotiation(vector):
    negotiation = protocol.negotiate_hello(
        _bytes(vector),
        authenticated_role=vector["admitted_role"],
        broker_product_version=vector["broker_product_version"],
    )

    assert negotiation.state.protocol_version == vector["expect_selected_version"]
    assert negotiation.state.role == vector["admitted_role"]
    if "expect_response_json" in vector:
        assert (
            protocol.canonical_json_bytes(negotiation.response).decode("utf-8")
            == vector["expect_response_json"]
        )


@pytest.mark.parametrize(
    "vector",
    [item for item in FIXTURES["hello_vectors"] if "expect_error" in item],
    ids=lambda item: item["name"],
)
def test_invalid_hello_fails_closed_with_fixed_error(vector):
    with pytest.raises(protocol.ProtocolError) as exc_info:
        protocol.negotiate_hello(
            _bytes(vector),
            authenticated_role=vector["admitted_role"],
            broker_product_version=vector.get("broker_product_version", "8.8.8-test"),
        )

    assert exc_info.value.code == vector["expect_error"]
    assert str(exc_info.value) == vector["expect_error"]


def test_claimed_role_is_never_sufficient_without_authenticated_role():
    vector = FIXTURES["hello_vectors"][0]
    with pytest.raises(TypeError):
        protocol.negotiate_hello(  # type: ignore[call-arg]
            _bytes(vector),
            broker_product_version="8.8.8-test",
        )


def test_negotiated_authority_cannot_be_constructed_or_mutated_by_a_role_string():
    with pytest.raises(TypeError):
        protocol.ConnectionState(  # type: ignore[call-arg]
            role="maintenance",
            protocol_version=1,
            seen_request_ids=set(),
        )
    state = _state("desktop")
    with pytest.raises((AttributeError, TypeError)):
        state.role = "maintenance"  # type: ignore[misc]


def test_hello_is_mandatory_first_and_cannot_repeat():
    request = _bytes(FIXTURES["request_vectors"][0])
    with pytest.raises(protocol.ProtocolError, match="request_invalid"):
        protocol.negotiate_hello(
            request,
            authenticated_role="desktop",
            broker_product_version="8.8.8-test",
        )

    hello = _bytes(FIXTURES["hello_vectors"][0])
    with pytest.raises(protocol.ProtocolError, match="request_invalid"):
        protocol.validate_request(
            hello,
            state=_state("desktop"),
            remote_tner=False,
        )


def test_authoritative_hello_and_message_frames_are_exact_bytes():
    vectors = [
        FIXTURES["hello_vectors"][0],
        FIXTURES["request_vectors"][0],
        FIXTURES["response_vectors"][0],
    ]
    for vector in vectors:
        assert protocol.encode_frame(_bytes(vector)) == bytes.fromhex(vector["frame_hex"])


def test_hello_decoder_is_capped_single_frame_and_switches_after_negotiation():
    hello = bytes.fromhex(FIXTURES["hello_vectors"][0]["frame_hex"])
    request = bytes.fromhex(FIXTURES["request_vectors"][0]["frame_hex"])
    hello_decoder = protocol.FrameDecoder.for_hello()
    assert hello_decoder.feed(hello) == [hello[4:]]
    hello_decoder.finish()

    request_decoder = protocol.FrameDecoder()
    assert request_decoder.feed(request) == [request[4:]]
    request_decoder.finish()

    with pytest.raises(protocol.ProtocolError, match="request_invalid"):
        protocol.FrameDecoder.for_hello().feed(hello + request)


def test_post_hello_decoder_accepts_partial_input_and_multiple_frames():
    request = bytes.fromhex(FIXTURES["request_vectors"][0]["frame_hex"])
    response = bytes.fromhex(FIXTURES["response_vectors"][0]["frame_hex"])
    decoder = protocol.FrameDecoder()
    decoded: list[bytes] = []
    for byte in request + response:
        decoded.extend(decoder.feed(bytes([byte])))
    decoder.finish()
    assert decoded == [request[4:], response[4:]]


@pytest.mark.parametrize(
    "vector",
    FIXTURES["hello_frame_vectors"],
    ids=lambda item: item["name"],
)
def test_pre_hello_frame_limit_is_enforced_before_body_copy(vector):
    decoder = protocol.FrameDecoder.for_hello()
    prefix = int(vector["declared_length"]).to_bytes(4, "big")
    if vector["valid"]:
        assert decoder.feed(prefix) == []
        with pytest.raises(protocol.ProtocolError, match="request_invalid"):
            decoder.finish()
        return

    class RecordingBuffer(bytearray):
        max_growth_bytes = 0

        def extend(self, value):
            self.max_growth_bytes = max(self.max_growth_bytes, len(value))
            super().extend(value)

    recording_buffer = RecordingBuffer()
    decoder._buffer = recording_buffer
    attached = bytes.fromhex(vector.get("attached_body_hex", ""))
    with pytest.raises(protocol.ProtocolError) as exc_info:
        decoder.feed(prefix + attached)
    assert exc_info.value.code == vector["expect_error"]
    assert recording_buffer.max_growth_bytes <= vector["expect_max_buffer_growth_bytes"]


@pytest.mark.parametrize(
    "vector",
    FIXTURES["frame_length_vectors"],
    ids=lambda item: item["name"],
)
def test_production_frame_length_boundary_is_pinned_without_allocating_body(vector):
    if vector["valid"]:
        protocol.validate_declared_length(vector["declared_length"])
    else:
        with pytest.raises(protocol.ProtocolError) as exc_info:
            protocol.validate_declared_length(vector["declared_length"])
        assert exc_info.value.code == vector["expect_error"]


@pytest.mark.parametrize(
    "vector",
    FIXTURES["partial_frame_vectors"],
    ids=lambda item: item["name"],
)
def test_partial_and_oversized_frames_fail_closed(vector):
    decoder = protocol.FrameDecoder(max_frame_bytes=vector.get("max_frame_bytes"))
    recording_buffer = None
    if "expect_max_buffer_growth_bytes" in vector:

        class RecordingBuffer(bytearray):
            max_growth_bytes = 0

            def extend(self, value):
                self.max_growth_bytes = max(self.max_growth_bytes, len(value))
                super().extend(value)

        recording_buffer = RecordingBuffer()
        decoder._buffer = recording_buffer
    if "expect_error" in vector:
        with pytest.raises(protocol.ProtocolError) as exc_info:
            decoder.feed(bytes.fromhex(vector["hex"]))
        assert exc_info.value.code == vector["expect_error"]
        if recording_buffer is not None:
            assert recording_buffer.max_growth_bytes <= vector["expect_max_buffer_growth_bytes"]
    else:
        assert decoder.feed(bytes.fromhex(vector["hex"])) == []
        with pytest.raises(protocol.ProtocolError) as exc_info:
            decoder.finish()
        assert exc_info.value.code == vector["expect_error_at_eof"]


@pytest.mark.parametrize(
    "vector",
    FIXTURES["invalid_decoder_limits"],
    ids=lambda item: item["name"],
)
def test_invalid_decoder_limits_fail_closed(vector):
    with pytest.raises(protocol.ProtocolError) as exc_info:
        protocol.FrameDecoder(max_frame_bytes=vector["max_frame_bytes"])
    assert exc_info.value.code == vector["expect_error"]


def test_zero_length_and_invalid_utf8_are_request_invalid():
    with pytest.raises(protocol.ProtocolError, match="request_invalid"):
        protocol.FrameDecoder().feed(b"\x00\x00\x00\x00")
    with pytest.raises(protocol.ProtocolError, match="request_invalid"):
        protocol.parse_canonical_object(b'{"value":"\xff"}')


@pytest.mark.parametrize(
    "vector",
    FIXTURES["json_depth_vectors"],
    ids=lambda item: item["name"],
)
def test_json_container_depth_is_bounded_before_parsing(vector):
    raw = str(vector["json"]).encode()
    if vector["valid"]:
        protocol.parse_canonical_object(raw)
    else:
        with pytest.raises(protocol.ProtocolError) as exc_info:
            protocol.parse_canonical_object(raw)
        assert exc_info.value.code == vector["expect_error"]
    assert vector["max_container_depth"] == CONTRACT_FILE["serialization"]["max_container_depth"]


def test_deep_python_values_collapse_to_fixed_protocol_error():
    value: object = 0
    for _ in range(CONTRACT_FILE["serialization"]["max_container_depth"]):
        value = [value]
    with pytest.raises(protocol.ProtocolError, match="request_invalid"):
        protocol.canonical_json_bytes({"value": value})


@pytest.mark.parametrize(
    "vector",
    FIXTURES["request_vectors"],
    ids=lambda item: item["name"],
)
def test_request_envelope_role_payload_and_deadline_conformance(vector):
    state = _state(vector["role"])
    if "expect_error" in vector:
        with pytest.raises(protocol.ProtocolError) as exc_info:
            protocol.validate_request(
                _bytes(vector),
                state=state,
                remote_tner=vector["remote_tner"],
            )
        assert exc_info.value.code == vector["expect_error"]
    else:
        request = protocol.validate_request(
            _bytes(vector),
            state=state,
            remote_tner=vector["remote_tner"],
        )
        assert request.operation == vector["operation"]
        assert request.deadline_ms == protocol.deadline_ms(
            vector["operation"],
            remote_tner=vector["remote_tner"],
        )
        assert request.replay == "never"


def test_request_ids_are_single_use_for_connection_lifetime():
    vector = FIXTURES["request_vectors"][0]
    state = _state("desktop")
    protocol.validate_request(_bytes(vector), state=state, remote_tner=False)
    with pytest.raises(protocol.ProtocolError, match="request_invalid"):
        protocol.validate_request(_bytes(vector), state=state, remote_tner=False)

    hello_id_state = _state("desktop", hello_request_id="request-1")
    with pytest.raises(protocol.ProtocolError, match="request_invalid"):
        protocol.validate_request(_bytes(vector), state=hello_id_state, remote_tner=False)


@pytest.mark.parametrize(
    "vector",
    FIXTURES["request_id_sequence_vectors"],
    ids=lambda item: item["name"],
)
def test_rejected_requests_consume_valid_request_ids(vector):
    state = _state(vector["role"])
    with pytest.raises(protocol.ProtocolError) as first_error:
        protocol.validate_request(
            str(vector["first_json"]).encode(),
            state=state,
            remote_tner=vector["remote_tner"],
        )
    assert first_error.value.code == vector["first_error"]

    with pytest.raises(protocol.ProtocolError) as second_error:
        protocol.validate_request(
            str(vector["second_json"]).encode(),
            state=state,
            remote_tner=vector["remote_tner"],
        )
    assert second_error.value.code == vector["second_error"]


def test_connection_message_limit_is_terminal_and_bounds_duplicate_work():
    limit = next(
        vector["limit"]
        for vector in FIXTURES["field_boundary_vectors"]
        if vector["field"] == "connection_messages"
    )
    state = _state("desktop")
    for index in range(1, limit - 1):
        message = protocol.canonical_json_bytes(
            {
                "broker_protocol_version": 1,
                "operation": "broker_health",
                "payload": {},
                "request_id": f"bounded-{index}",
            }
        )
        protocol.validate_request(message, state=state, remote_tner=False)

    with pytest.raises(protocol.ProtocolError, match="request_invalid"):
        protocol.validate_request(b"{}", state=state, remote_tner=False)

    duplicate_at_limit = protocol.canonical_json_bytes(
        {
            "broker_protocol_version": 1,
            "operation": "broker_health",
            "payload": {},
            "request_id": "bounded-1",
        }
    )
    with pytest.raises(protocol.ProtocolError, match="broker_busy"):
        protocol.validate_request(duplicate_at_limit, state=state, remote_tner=False)
    over_limit = protocol.canonical_json_bytes(
        {
            "broker_protocol_version": 1,
            "operation": "broker_health",
            "payload": {},
            "request_id": "bounded-over-limit",
        }
    )
    with pytest.raises(protocol.ProtocolError, match="broker_unavailable"):
        protocol.validate_request(over_limit, state=state, remote_tner=False)


def test_remote_tner_text_boundary_uses_one_existing_core_chunk():
    base = {
        "broker_protocol_version": 1,
        "operation": "detect",
        "payload": {"text": "x" * 500},
        "request_id": "tner-boundary",
        "scope_id": "scope-1",
    }
    raw = protocol.canonical_json_bytes(base)
    request = protocol.validate_request(raw, state=_state("desktop"), remote_tner=True)
    assert len(request.payload["text"]) == 500
    assert request.remote_tner_max_calls == 501
    assert request.remote_tner_text_chars == 500
    assert request.local_detection_phases is None
    assert request.local_intermediate_text_chars is None

    base["payload"]["text"] += "x"
    with pytest.raises(protocol.ProtocolError, match="payload_too_large"):
        protocol.validate_request(
            protocol.canonical_json_bytes(base),
            state=_state("desktop"),
            remote_tner=True,
        )


@pytest.mark.parametrize("operation", ["sanitize", "reidentify", "roundtrip"])
def test_remote_tner_is_disabled_when_current_path_can_scan_non_source_text(operation):
    payloads = {
        "sanitize": {"text": "synthetic source"},
        "reidentify": {"session_id": "synthetic-session", "text": "synthetic masked text"},
        "roundtrip": {
            "mode": "token",
            "provider": "ollama",
            "text": "synthetic source",
        },
    }
    message = protocol.canonical_json_bytes(
        {
            "broker_protocol_version": 1,
            "operation": operation,
            "payload": payloads[operation],
            "request_id": f"remote-disabled-{operation}",
            "scope_id": "scope-1",
        }
    )
    with pytest.raises(protocol.ProtocolError, match="ner_unavailable"):
        protocol.validate_request(message, state=_state("desktop"), remote_tner=True)


def test_local_text_boundary_is_200000_unicode_code_points():
    message = {
        "broker_protocol_version": 1,
        "operation": "sanitize",
        "payload": {"text": "ก" * 200000},
        "request_id": "local-boundary",
        "scope_id": "scope-1",
    }
    request = protocol.validate_request(
        protocol.canonical_json_bytes(message),
        state=_state("desktop"),
        remote_tner=False,
    )
    assert len(request.payload["text"]) == 200000
    assert request.local_detection_phases == 2
    assert request.local_intermediate_text_chars == 200000

    message["payload"]["text"] += "ก"
    with pytest.raises(protocol.ProtocolError, match="payload_too_large"):
        protocol.validate_request(
            protocol.canonical_json_bytes(message),
            state=_state("desktop"),
            remote_tner=False,
        )


@pytest.mark.parametrize(
    "vector",
    FIXTURES["response_vectors"],
    ids=lambda item: item["name"],
)
def test_response_envelope_conformance(vector):
    if "expect_error" in vector:
        with pytest.raises(protocol.ProtocolError) as exc_info:
            protocol.validate_response(
                _bytes(vector),
                role=vector["role"],
                operation=vector["operation"],
                request_id=vector["request_id"],
            )
        assert exc_info.value.code == vector["expect_error"]
    else:
        response = protocol.validate_response(
            _bytes(vector),
            role=vector["role"],
            operation=vector["operation"],
            request_id=vector["request_id"],
        )
        assert response["result"] == {"status": "ok"}


@pytest.mark.parametrize(
    "vector",
    FIXTURES["success_builder_vectors"],
    ids=lambda item: f"{item['operation']}-v{item['protocol_version']}",
)
def test_success_builder_never_emits_an_unnegotiated_version(vector):
    if "expect_error" in vector:
        with pytest.raises(protocol.ProtocolError) as exc_info:
            protocol.success_message(
                vector["operation"],
                request_id=vector["request_id"],
                result=vector["result"],
                role=vector["role"],
                protocol_version=vector["protocol_version"],
            )
        assert exc_info.value.code == vector["expect_error"]
        return

    message = protocol.success_message(
        vector["operation"],
        request_id=vector["request_id"],
        result=vector["result"],
        role=vector["role"],
        protocol_version=vector["protocol_version"],
    )
    assert protocol.canonical_json_bytes(message).decode("utf-8") == vector["expect_json"]


def test_python_builders_do_not_treat_boolean_as_protocol_version_one():
    with pytest.raises(protocol.ProtocolError, match="operation_failed"):
        protocol.success_message(
            "broker_health",
            request_id="boolean-version",
            result={"status": "ok"},
            role="desktop",
            protocol_version=True,  # type: ignore[arg-type]
        )
    error = protocol.error_message(
        "operation_failed",
        request_id="boolean-version",
        protocol_version=True,  # type: ignore[arg-type]
    )
    assert type(error["broker_protocol_version"]) is int
    assert error["broker_protocol_version"] == 1


@pytest.mark.parametrize(
    "vector",
    FIXTURES["result_schema_vectors"],
    ids=lambda item: item["operation"],
)
def test_every_operation_result_schema_is_shared_and_deeply_strict(vector):
    message = protocol.success_message(
        vector["operation"],
        request_id=vector["request_id"],
        result=vector["result"],
        role=vector["role"],
    )
    raw = protocol.canonical_json_bytes(message)
    assert (
        protocol.validate_response(
            raw,
            role=vector["role"],
            operation=vector["operation"],
            request_id=vector["request_id"],
        )
        == message
    )


def test_result_schema_vectors_cover_every_operation():
    assert {vector["operation"] for vector in FIXTURES["result_schema_vectors"]} == set(
        protocol.CONTRACT["operations"]
    )


@pytest.mark.parametrize(
    "vector",
    FIXTURES["result_mutation_vectors"],
    ids=lambda item: f"{item['operation']}-{'.'.join(item['path'])}",
)
def test_shared_result_schema_mutations_fail_closed(vector):
    source = next(
        item
        for item in FIXTURES["result_schema_vectors"]
        if item["operation"] == vector["operation"]
    )
    result = copy.deepcopy(source["result"])
    target = result
    for segment in vector["path"][:-1]:
        target = target[segment]
    target[vector["path"][-1]] = vector["value"]
    with pytest.raises(protocol.ProtocolError) as exc_info:
        protocol.success_message(
            vector["operation"],
            request_id="result-mutation",
            result=result,
            role=source["role"],
        )
    assert exc_info.value.code == vector["expect_error"]


@pytest.mark.parametrize(
    "vector",
    FIXTURES["error_messages"],
    ids=lambda item: item["code"],
)
def test_every_fixed_error_shape_is_exact_and_accepted(vector):
    message = protocol.error_message(vector["code"], request_id="error-1")
    assert protocol.canonical_json_bytes(message).decode("utf-8") == vector["json"]
    assert (
        protocol.validate_response(
            vector["json"].encode("utf-8"),
            role="desktop",
            operation="broker_health",
            request_id="error-1",
        )
        == message
    )


@pytest.mark.parametrize("vector", FIXTURES["uncorrelated_error_vectors"])
def test_uncorrelated_and_unknown_failures_have_one_safe_shape(vector):
    message = protocol.error_message(vector["code"], request_id=None)
    assert protocol.canonical_json_bytes(message).decode("utf-8") == vector["json"]


def test_unknown_internal_failure_collapses_without_value_or_exception_type():
    sentinel = "SYNTHETIC_SECRET_SENTINEL"
    assert protocol.safe_error_code(sentinel) == "operation_failed"
    error = protocol.ProtocolError("request_invalid", "private-request-id")
    assert sentinel not in str(error)
    assert sentinel not in repr(error)
    assert "private-request-id" not in repr(error)
    assert set(vars(error)) <= {"code", "request_id"}


def test_invalid_authenticated_state_types_fail_closed_without_runtime_leaks():
    vector = FIXTURES["hello_vectors"][0]
    with pytest.raises(protocol.ProtocolError, match="broker_unauthorized"):
        protocol.negotiate_hello(
            _bytes(vector),
            authenticated_role=[],  # type: ignore[arg-type]
            broker_product_version="8.8.8-test",
        )
    with pytest.raises(protocol.ProtocolError, match="broker_unauthorized"):
        protocol.validate_request(
            _bytes(FIXTURES["request_vectors"][0]),
            state=object(),  # type: ignore[arg-type]
            remote_tner=False,
        )


def test_closed_role_operation_policy_is_exhaustive():
    policy = FIXTURES["role_operation_policy"]
    assert set(policy["operations"]) == set(CONTRACT_FILE["operations"])
    assert set(policy["allowlists"]) == set(CONTRACT_FILE["roles"])

    for role, allowed in policy["allowlists"].items():
        for operation in policy["operations"]:
            assert protocol.operation_allowed(role, operation) is (operation in allowed)
    for role in policy["unknown_roles"]:
        for operation in policy["operations"]:
            assert not protocol.operation_allowed(role, operation)
    for role in policy["allowlists"]:
        for operation in policy["unknown_operations"]:
            assert not protocol.operation_allowed(role, operation)


@pytest.mark.parametrize(
    "vector",
    FIXTURES["deadline_vectors"],
    ids=lambda item: f"{item['operation']}-tner-{item['remote_tner']}",
)
def test_deadline_table(vector):
    assert (
        protocol.deadline_ms(vector["operation"], remote_tner=vector["remote_tner"])
        == vector["deadline_ms"]
    )


def test_remote_tner_operation_budgets_are_exhaustive_and_bounded():
    vectors = {vector["operation"]: vector for vector in FIXTURES["remote_tner_budget_vectors"]}
    assert set(vectors) == set(CONTRACT_FILE["operations"])
    assert {
        operation
        for operation, vector in vectors.items()
        if vector["primary_scans"] not in (None, 0)
    } == set(CONTRACT_FILE["remote_tner_policy"]["source_only_operations"])
    assert {
        operation for operation, vector in vectors.items() if vector["deadline_ms"] is None
    } == set(CONTRACT_FILE["remote_tner_policy"]["disabled_operations"])
    calls_per_scan = CONTRACT_FILE["field_limits"]["remote_tner_calls_per_scan"]
    for operation, vector in vectors.items():
        spec = CONTRACT_FILE["operations"][operation]
        assert spec["remote_tner_primary_scans"] == vector["primary_scans"]
        assert spec["remote_tner_max_calls"] == vector["max_calls"]
        assert protocol.deadline_ms(operation, remote_tner=True) == vector["deadline_ms"]
        if vector["primary_scans"] is not None:
            assert vector["max_calls"] == vector["primary_scans"] * calls_per_scan


def test_local_detection_phase_budgets_and_intermediate_cap_are_pinned():
    phase_vectors = {
        vector["operation"]: vector for vector in FIXTURES["local_detection_phase_vectors"]
    }
    assert set(phase_vectors) == set(CONTRACT_FILE["operations"])
    for operation, vector in phase_vectors.items():
        spec = CONTRACT_FILE["operations"][operation]
        assert spec["local_detection_phases"] == vector["phases"]
        assert protocol.deadline_ms(operation, remote_tner=False) == vector["deadline_ms"]
    assert (
        CONTRACT_FILE["field_limits"]["local_intermediate_text_chars"]
        == CONTRACT_FILE["field_limits"]["text_chars"]
        == 200000
    )


def test_replay_and_uncertain_completion_policy_is_exhaustive():
    vectors = {vector["operation"]: vector for vector in FIXTURES["replay_and_mutation_vectors"]}
    assert set(vectors) == set(CONTRACT_FILE["operations"])
    for operation, vector in vectors.items():
        spec = CONTRACT_FILE["operations"][operation]
        assert protocol.operation_replay(operation) == vector["replay"]
        assert spec["uncertain_completion"] == vector["uncertain_completion"]

    for index, optional in enumerate(({}, {"session_id": "synthetic-session"}), start=1):
        request = protocol.validate_request(
            protocol.canonical_json_bytes(
                {
                    "broker_protocol_version": 1,
                    "operation": "sanitize",
                    "payload": {"text": "synthetic source", **optional},
                    "request_id": f"sanitize-mutation-{index}",
                    "scope_id": "scope-1",
                }
            ),
            state=_state("desktop"),
            remote_tner=False,
        )
        assert (
            request.uncertain_completion == "possible_session_publication_or_known_session_mutation"
        )


def test_limit_rationale_arithmetic_and_shared_boundary_vectors():
    framing = protocol.CONTRACT["framing"]
    assert framing["max_pdf_base64_bytes"] == 4 * ((framing["max_pdf_raw_bytes"] + 2) // 3)
    assert framing["max_frame_bytes"] == (
        framing["max_pdf_base64_bytes"] + framing["default_message_bytes"]
    )
    limits = {
        (item["field"], item["profile"]): item["limit"]
        for item in FIXTURES["field_boundary_vectors"]
    }
    assert limits[("text", "local")] == protocol.CONTRACT["field_limits"]["text_chars"]
    assert (
        limits[("text", "remote_tner")]
        == protocol.CONTRACT["field_limits"]["remote_tner_text_chars"]
    )
    assert (
        limits[("remote_tner_calls_per_scan", "remote_tner")]
        == protocol.CONTRACT["field_limits"]["remote_tner_calls_per_scan"]
        == 501
    )
    assert protocol.deadline_ms("sanitize", remote_tner=True) is None
    assert protocol.deadline_ms("roundtrip", remote_tner=False) == (
        6 * 360_000 + 3 * 60_000 + 1_000 + 2_000 + 5_000
    )
    assert limits[("connection_messages", "connection")] == 4096
    assert limits[("extension_response_bytes", "extension")] == framing["extension_response_bytes"]


def test_extension_success_boundary_is_exact_and_never_truncated():
    limit = protocol.CONTRACT["framing"]["extension_response_bytes"]
    result = {
        "detected_entity_count": 0,
        "entity_type_counts": {},
        "guard_findings": [],
        "highlights": [],
        "replacement_count": 0,
        "safety": {"residual_count": 0, "status": "pass"},
        "sanitized_text": "x",
        "section26_categories": [],
        "session_id": "synthetic-session",
        "warnings": [],
    }
    base = protocol.success_message(
        "sanitize",
        request_id="extension-boundary",
        result=result,
        role="extension",
    )
    filler = limit - len(protocol.canonical_json_bytes(base))
    assert filler > 0
    result["sanitized_text"] += "x" * filler
    boundary = protocol.success_message(
        "sanitize",
        request_id="extension-boundary",
        result=result,
        role="extension",
    )
    assert len(protocol.canonical_json_bytes(boundary)) == limit

    result["sanitized_text"] += "x"
    with pytest.raises(protocol.ProtocolError, match="payload_too_large"):
        protocol.success_message(
            "sanitize",
            request_id="extension-boundary",
            result=result,
            role="extension",
        )


def test_only_startup_health_is_repeatable_and_unsafe_remote_tner_paths_are_disabled():
    assert protocol.operation_replay("broker_health") == "startup_only"
    assert all(
        protocol.operation_replay(operation) == "never"
        for operation in protocol.CONTRACT["operations"]
        if operation != "broker_health"
    )
    assert all(
        protocol.deadline_ms(operation, remote_tner=True) is None
        for operation in ("redact_pdf", "reidentify", "roundtrip", "sanitize")
    )


@pytest.mark.parametrize(
    "value",
    [
        b'{"a":1.0}',
        b'{"a":-0}',
        b'{"a":9007199254740992}',
        b'{"a":"\\u0e01"}',
        b'{"b":1,"a":2}',
        b'{"a":1,"a":1}',
        b' {"a":1}',
        b'{"a":1}\n',
    ],
)
def test_noncanonical_or_ambiguous_json_is_rejected(value):
    with pytest.raises(protocol.ProtocolError, match="request_invalid"):
        protocol.parse_canonical_object(value)


def test_canonical_unicode_and_nested_objects_round_trip_exactly():
    value = {"array": [{"count": 1}], "text": "ก😀"}
    encoded = protocol.canonical_json_bytes(value)
    assert encoded == '{"array":[{"count":1}],"text":"ก😀"}'.encode()
    assert protocol.parse_canonical_object(encoded) == value


def test_malformed_sentinel_input_never_reaches_error_or_logs(capsys, caplog):
    sentinel = "SYNTHETIC_PROTOCOL_SENTINEL"
    raw = protocol.canonical_json_bytes(
        {
            "broker_protocol_version": 1,
            "operation": "sanitize",
            "payload": {"extra": sentinel, "text": "synthetic text"},
            "request_id": sentinel,
            "scope_id": "scope-1",
        }
    )
    with pytest.raises(protocol.ProtocolError) as exc_info:
        protocol.validate_request(raw, state=_state("desktop"), remote_tner=False)
    captured = capsys.readouterr()
    assert sentinel not in str(exc_info.value)
    assert sentinel not in repr(exc_info.value)
    assert sentinel not in captured.out
    assert sentinel not in captured.err
    assert all(sentinel not in record.getMessage() for record in caplog.records)
    traceback = exc_info.value.__traceback__
    while traceback is not None:
        if (
            Path(traceback.tb_frame.f_code.co_filename).resolve()
            == Path(protocol.__file__).resolve()
        ):
            if "failure" in traceback.tb_frame.f_locals:
                assert traceback.tb_frame.f_locals["failure"] is None
            assert all(
                sentinel not in repr(value) for value in traceback.tb_frame.f_locals.values()
            )
        traceback = traceback.tb_next

    valid_raw = protocol.canonical_json_bytes(
        {
            "broker_protocol_version": 1,
            "operation": "sanitize",
            "payload": {"text": sentinel},
            "request_id": "private-request-id",
            "scope_id": "private-scope-id",
        }
    )
    request = protocol.validate_request(
        valid_raw,
        state=_state("desktop"),
        remote_tner=False,
    )
    rendered = repr(request)
    assert sentinel not in rendered
    assert "private-request-id" not in rendered
    assert "private-scope-id" not in rendered

    decoder = protocol.FrameDecoder()
    buffered = sentinel.encode("ascii")
    decoder.feed((len(buffered) + 1).to_bytes(4, "big") + buffered)
    assert sentinel not in repr(decoder)


def test_all_public_value_validators_discard_sensitive_traceback_locals():
    sentinel = "SYNTHETIC_TRACEBACK_SENTINEL"

    def assert_safe_traceback(call):
        with pytest.raises(protocol.ProtocolError) as exc_info:
            call()
        traceback = exc_info.value.__traceback__
        while traceback is not None:
            if (
                Path(traceback.tb_frame.f_code.co_filename).resolve()
                == Path(protocol.__file__).resolve()
            ):
                if "failure" in traceback.tb_frame.f_locals:
                    assert traceback.tb_frame.f_locals["failure"] is None
                assert all(
                    sentinel not in repr(value) for value in traceback.tb_frame.f_locals.values()
                )
            traceback = traceback.tb_next

    assert_safe_traceback(
        lambda: protocol.canonical_json_bytes({"private": sentinel, "unsupported": 1.5})
    )
    noncanonical = f'{{"z":"{sentinel}","a":1}}'.encode()
    assert_safe_traceback(lambda: protocol.parse_canonical_object(noncanonical))
    assert_safe_traceback(lambda: protocol.encode_frame(noncanonical))
    hello = protocol.canonical_json_bytes(
        {
            "claimed_role": "desktop",
            "client_product_version": "9.9.9-test",
            "extra": sentinel,
            "request_id": sentinel,
            "supported_protocol_versions": [1],
        }
    )
    assert_safe_traceback(
        lambda: protocol.negotiate_hello(
            hello,
            authenticated_role="desktop",
            broker_product_version="8.8.8-test",
        )
    )
    assert_safe_traceback(
        lambda: protocol.success_message(
            "broker_health",
            request_id=sentinel,
            result={"extra": sentinel, "status": "ok"},
            role="desktop",
        )
    )
    response = protocol.canonical_json_bytes(
        {
            "broker_protocol_version": 1,
            "extra": sentinel,
            "request_id": sentinel,
            "result": {"status": "ok"},
        }
    )
    assert_safe_traceback(
        lambda: protocol.validate_response(
            response,
            role="desktop",
            operation="broker_health",
            request_id=sentinel,
        )
    )
    assert_safe_traceback(
        lambda: protocol.FrameDecoder(max_frame_bytes=5).feed(
            b"\x00\x00\x00\x06" + sentinel.encode()
        )
    )
