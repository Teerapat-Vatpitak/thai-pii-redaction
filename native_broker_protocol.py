"""Transport-free native-broker protocol v1 codec and policy.

This module defines framing, canonical JSON, negotiation, envelopes, limits,
deadlines, and role/operation authorization. It opens no endpoint and performs
no backend or storefront operation.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTRACT_PATH = Path(__file__).resolve().parent / "native-broker" / "protocol-v1.json"
CONTRACT: dict[str, Any] = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PRODUCT_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")
_PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_DATA_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$")
_JSON_INTEGER_MAX = int(CONTRACT["field_limits"]["json_integer_max"])
_SERIALIZATION = CONTRACT.get("serialization", {})
_MAX_CONTAINER_DEPTH = _SERIALIZATION.get("max_container_depth")
_BLANK_TEXT_CODE_POINTS = frozenset(_SERIALIZATION.get("blank_text_code_points", []))
_CONNECTION_STATE_TOKEN = object()


class ProtocolError(ValueError):
    """A fixed value-free protocol failure."""

    def __init__(self, code: str, request_id: str | None = None) -> None:
        self.code = safe_error_code(code)
        self.request_id = request_id if _valid_id(request_id) else None
        super().__init__(self.code)

    def __repr__(self) -> str:
        return f"ProtocolError({self.code!r})"


@dataclass(frozen=True, repr=False)
class _CapturedProtocolFailure:
    code: str
    request_id: str | None


def _capture_protocol_call(call):
    try:
        return call(), None
    except ProtocolError as error:
        failure = _CapturedProtocolFailure(error.code, error.request_id)
        error.__traceback__ = None
        return None, failure
    except Exception as error:
        error.__traceback__ = None
        return None, _CapturedProtocolFailure("operation_failed", None)


@dataclass(frozen=True, init=False, repr=False)
class ConnectionState:
    """Negotiated connection metadata; authenticated identity stays external."""

    _role: str
    _protocol_version: int
    _seen_request_ids: set[str]
    _messages_seen: int
    _terminal: bool

    def __init__(
        self,
        *,
        _creation_token: object,
        role: str,
        protocol_version: int,
        seen_request_ids: set[str],
    ) -> None:
        if _creation_token is not _CONNECTION_STATE_TOKEN:
            raise TypeError("connection state requires successful negotiation")
        object.__setattr__(self, "_role", role)
        object.__setattr__(self, "_protocol_version", protocol_version)
        object.__setattr__(self, "_seen_request_ids", set(seen_request_ids))
        object.__setattr__(self, "_messages_seen", 1)
        object.__setattr__(self, "_terminal", False)

    @property
    def role(self) -> str:
        return self._role

    @property
    def protocol_version(self) -> int:
        return self._protocol_version

    @property
    def terminal(self) -> bool:
        return self._terminal

    def _has_request_id(self, request_id: str) -> bool:
        return request_id in self._seen_request_ids

    def _admit_message(self) -> bool:
        if self._messages_seen >= int(CONTRACT["field_limits"]["connection_messages"]):
            object.__setattr__(self, "_terminal", True)
            return False
        object.__setattr__(self, "_messages_seen", self._messages_seen + 1)
        return True

    def _record_request_id(self, request_id: str) -> None:
        self._seen_request_ids.add(request_id)

    def __repr__(self) -> str:
        return f"ConnectionState(role={self._role!r}, protocol_version={self._protocol_version})"


@dataclass(frozen=True, repr=False)
class HelloNegotiation:
    state: ConnectionState
    response: dict[str, Any]

    def __repr__(self) -> str:
        return (
            "HelloNegotiation("
            f"role={self.state.role!r}, protocol_version={self.state.protocol_version}"
            ")"
        )


@dataclass(frozen=True, repr=False)
class BrokerRequest:
    protocol_version: int
    request_id: str
    operation: str
    scope_id: str | None
    payload: dict[str, Any]
    deadline_ms: int | None
    local_detection_phases: int | None
    local_intermediate_text_chars: int | None
    remote_tner_max_calls: int
    remote_tner_text_chars: int | None
    replay: str
    uncertain_completion: str

    def __repr__(self) -> str:
        return (
            "BrokerRequest("
            f"protocol_version={self.protocol_version}, "
            f"operation={self.operation!r}, "
            f"deadline_ms={self.deadline_ms}, "
            f"local_detection_phases={self.local_detection_phases}, "
            f"remote_tner_max_calls={self.remote_tner_max_calls}, "
            f"replay={self.replay!r}, "
            f"uncertain_completion={self.uncertain_completion!r}"
            ")"
        )


def _validate_contract() -> None:
    if type(CONTRACT.get("contract_schema_version")) is not int or (
        CONTRACT["contract_schema_version"] != 1
    ):
        raise RuntimeError("invalid broker contract schema version")
    if CONTRACT.get("supported_protocol_versions") != [1]:
        raise RuntimeError("invalid broker protocol version table")
    framing = CONTRACT.get("framing")
    if not isinstance(framing, dict):
        raise RuntimeError("invalid broker framing table")
    if framing.get("length_prefix_bytes") != 4 or framing.get("byte_order") != "big":
        raise RuntimeError("invalid broker framing contract")
    if framing.get("max_pdf_base64_bytes") != 4 * ((framing.get("max_pdf_raw_bytes", 0) + 2) // 3):
        raise RuntimeError("invalid broker PDF base64 limit")
    if framing.get("max_frame_bytes") != (
        framing.get("max_pdf_base64_bytes", 0) + framing.get("default_message_bytes", 0)
    ):
        raise RuntimeError("invalid broker frame limit")
    operations = CONTRACT.get("operations")
    roles = CONTRACT.get("roles")
    errors = CONTRACT.get("errors")
    result_definitions = CONTRACT.get("result_schema_definitions")
    serialization = CONTRACT.get("serialization")
    if not all(
        isinstance(item, dict)
        for item in (operations, roles, errors, result_definitions, serialization)
    ):
        raise RuntimeError("invalid broker policy tables")
    max_depth = serialization.get("max_container_depth")
    blank_points = serialization.get("blank_text_code_points")
    if (
        type(max_depth) is not int
        or not 1 <= max_depth <= 64
        or not isinstance(blank_points, list)
        or blank_points != sorted(set(blank_points))
        or any(
            type(point) is not int or not 0 <= point <= 0x10FFFF or 0xD800 <= point <= 0xDFFF
            for point in blank_points
        )
    ):
        raise RuntimeError("invalid broker serialization table")
    if any(not isinstance(spec.get("result_schema"), dict) for spec in operations.values()):
        raise RuntimeError("invalid broker result schema table")
    calls_per_scan = CONTRACT["field_limits"].get("remote_tner_calls_per_scan")
    connection_messages = CONTRACT["field_limits"].get("connection_messages")
    local_intermediate_text_chars = CONTRACT["field_limits"].get("local_intermediate_text_chars")
    if (
        type(calls_per_scan) is not int
        or calls_per_scan <= 0
        or type(connection_messages) is not int
        or connection_messages <= 1
        or local_intermediate_text_chars != CONTRACT["field_limits"].get("text_chars")
    ):
        raise RuntimeError("invalid broker bounded-state table")
    disabled_remote = CONTRACT.get("remote_tner_policy", {}).get("disabled_operations")
    source_only_remote = CONTRACT.get("remote_tner_policy", {}).get("source_only_operations")
    if (
        not isinstance(disabled_remote, list)
        or not isinstance(source_only_remote, list)
        or set(disabled_remote) != {"redact_pdf", "reidentify", "roundtrip", "sanitize"}
        or set(source_only_remote) != {"analyze", "analyze_report", "detect"}
    ):
        raise RuntimeError("invalid remote TNER policy")
    components = CONTRACT.get("deadline_components_ms")
    profiles = CONTRACT.get("deadline_profiles_ms")
    connection_policy = CONTRACT.get("connection_policy")
    local_detection_policy = CONTRACT.get("local_detection_policy")
    if not all(
        isinstance(item, dict)
        for item in (
            components,
            profiles,
            connection_policy,
            local_detection_policy,
        )
    ):
        raise RuntimeError("invalid broker deadline or connection policy")
    if (
        profiles.get("local_sanitize")
        != 2 * components.get("local_detection_phase", 0) + components.get("adapter", 0)
        or profiles.get("local_reidentify")
        != components.get("local_detection_phase", 0)
        + components.get("local_restore_and_disposal", 0)
        or profiles.get("local_provider")
        != 6 * components.get("local_detection_phase", 0)
        + 3 * components.get("provider_attempt", 0)
        + components.get("provider_backoff_total", 0)
        + components.get("adapter", 0)
        or profiles.get("remote_tner_text")
        != calls_per_scan * components.get("remote_tner_call", 0) + components.get("adapter", 0)
        or profiles.get("remote_tner_report")
        != profiles.get("remote_tner_text") + components.get("local_restore_and_disposal", 0)
    ):
        raise RuntimeError("invalid broker deadline arithmetic")
    policy_errors = {
        connection_policy.get("message_limit_error"),
        connection_policy.get("terminal_error"),
        local_detection_policy.get("intermediate_limit_error"),
        CONTRACT["remote_tner_policy"].get("unsupported_operation_error"),
    }
    if not policy_errors <= set(errors):
        raise RuntimeError("invalid broker policy error")
    positive_remote_operations = {
        operation
        for operation, spec in operations.items()
        if type(spec.get("remote_tner_primary_scans")) is int
        and spec["remote_tner_primary_scans"] > 0
    }
    null_remote_operations = {
        operation
        for operation, spec in operations.items()
        if spec.get("deadline_remote_tner") is None
    }
    if positive_remote_operations != set(source_only_remote) or null_remote_operations != set(
        disabled_remote
    ):
        raise RuntimeError("invalid closed remote TNER operation classification")
    for operation, spec in operations.items():
        local_phases = spec.get("local_detection_phases")
        if local_phases is not None and (type(local_phases) is not int or local_phases < 0):
            raise RuntimeError("invalid local detection phase budget")
        primary_scans = spec.get("remote_tner_primary_scans")
        max_calls = spec.get("remote_tner_max_calls")
        remote_deadline = spec.get("deadline_remote_tner")
        if remote_deadline is None:
            if primary_scans is not None or max_calls is not None:
                raise RuntimeError("invalid disabled remote TNER operation")
        elif (
            type(primary_scans) is not int
            or primary_scans < 0
            or type(max_calls) is not int
            or max_calls != primary_scans * calls_per_scan
        ):
            raise RuntimeError("invalid remote TNER operation budget")
        if operation in disabled_remote and remote_deadline is not None:
            raise RuntimeError("invalid enabled non-source remote TNER path")
        if operation in source_only_remote and (primary_scans != 1 or max_calls != calls_per_scan):
            raise RuntimeError("invalid source-only remote TNER budget")
    for role, allowed in roles.items():
        if role not in {"desktop", "extension", "maintenance"}:
            raise RuntimeError("invalid broker role")
        if not isinstance(allowed, list) or not set(allowed) <= set(operations):
            raise RuntimeError("invalid broker role-operation policy")
    for code, spec in errors.items():
        if (
            not isinstance(code, str)
            or not isinstance(spec, dict)
            or spec.get("retry") not in {"never", "reconnect_only"}
        ):
            raise RuntimeError("invalid broker error table")


_validate_contract()


def safe_error_code(code: object) -> str:
    """Collapse unknown/internal failures to one fixed broker error."""

    if isinstance(code, str) and code in CONTRACT.get("errors", {}):
        return code
    return "operation_failed"


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and _ID_RE.fullmatch(value) is not None


def _valid_product_version(value: object) -> bool:
    return isinstance(value, str) and _PRODUCT_VERSION_RE.fullmatch(value) is not None


def _validate_json_value(value: object) -> None:
    pending: list[tuple[object, int]] = [(value, 0)]
    while pending:
        item, container_depth = pending.pop()
        if item is None or isinstance(item, (str, bool)):
            if isinstance(item, str) and any(0xD800 <= ord(char) <= 0xDFFF for char in item):
                raise ProtocolError("request_invalid")
            continue
        if type(item) is int:
            if not 0 <= item <= _JSON_INTEGER_MAX:
                raise ProtocolError("request_invalid")
            continue
        if isinstance(item, list):
            next_depth = container_depth + 1
            if next_depth > _MAX_CONTAINER_DEPTH:
                raise ProtocolError("request_invalid")
            pending.extend((child, next_depth) for child in item)
            continue
        if isinstance(item, dict):
            next_depth = container_depth + 1
            if next_depth > _MAX_CONTAINER_DEPTH:
                raise ProtocolError("request_invalid")
            for key, child in item.items():
                if not isinstance(key, str) or any(0xD800 <= ord(char) <= 0xDFFF for char in key):
                    raise ProtocolError("request_invalid")
                pending.append((child, next_depth))
            continue
        raise ProtocolError("request_invalid")


def _canonical_json_bytes(value: object) -> bytes:
    """Serialize one v1 value in the unique compact UTF-8 representation."""

    _validate_json_value(value)
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ProtocolError("request_invalid") from None


def canonical_json_bytes(value: object) -> bytes:
    result, failure = _capture_protocol_call(lambda: _canonical_json_bytes(value))
    value = None
    if failure is not None:
        safe_error = ProtocolError(failure.code, failure.request_id)
        failure = None
        raise safe_error from None
    if not isinstance(result, bytes):
        result = None
        raise ProtocolError("operation_failed") from None
    return result


def _validate_raw_container_depth(raw: bytes) -> None:
    depth = 0
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in {0x5B, 0x7B}:
            depth += 1
            if depth > _MAX_CONTAINER_DEPTH:
                raise ProtocolError("request_invalid")
        elif byte in {0x5D, 0x7D}:
            depth -= 1
            if depth < 0:
                raise ProtocolError("request_invalid")


def _parse_canonical_object(
    raw: bytes,
    *,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Parse one exact canonical JSON object without retaining parser details."""

    if not isinstance(raw, bytes) or not raw:
        raise ProtocolError("request_invalid")
    if max_bytes is not None and len(raw) > max_bytes:
        raise ProtocolError("payload_too_large")
    _validate_raw_container_depth(raw)
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError, RecursionError):
        raise ProtocolError("request_invalid") from None
    text = ""
    if not isinstance(value, dict):
        value = None
        raise ProtocolError("request_invalid")
    try:
        encoded = canonical_json_bytes(value)
    except ProtocolError:
        value = None
        raise
    if encoded != raw:
        value = None
        encoded = b""
        raise ProtocolError("request_invalid")
    return value


def parse_canonical_object(
    raw: bytes,
    *,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    result, failure = _capture_protocol_call(
        lambda: _parse_canonical_object(raw, max_bytes=max_bytes)
    )
    raw = b""
    max_bytes = None
    if failure is not None:
        safe_error = ProtocolError(failure.code, failure.request_id)
        failure = None
        raise safe_error from None
    if not isinstance(result, dict):
        result = None
        raise ProtocolError("operation_failed") from None
    return result


def _effective_frame_limit(max_frame_bytes: int | None) -> int:
    production_limit = int(CONTRACT["framing"]["max_frame_bytes"])
    if max_frame_bytes is None:
        return production_limit
    if type(max_frame_bytes) is not int or max_frame_bytes <= 0:
        raise ProtocolError("request_invalid")
    return min(production_limit, max_frame_bytes)


def validate_declared_length(
    declared_length: int,
    max_frame_bytes: int | None = None,
) -> None:
    """Validate a prefix before allocating or reading its body."""

    if type(declared_length) is not int or declared_length <= 0:
        raise ProtocolError("request_invalid")
    if declared_length > _effective_frame_limit(max_frame_bytes):
        raise ProtocolError("payload_too_large")


def _encode_frame(
    message: bytes | dict[str, Any],
    max_frame_bytes: int | None = None,
) -> bytes:
    """Frame an already canonical message or a protocol object."""

    if isinstance(message, bytes):
        payload = message
        parse_canonical_object(payload, max_bytes=_effective_frame_limit(max_frame_bytes))
    elif isinstance(message, dict):
        payload = canonical_json_bytes(message)
    else:
        raise ProtocolError("request_invalid")
    validate_declared_length(len(payload), max_frame_bytes)
    return len(payload).to_bytes(4, "big") + payload


def encode_frame(
    message: bytes | dict[str, Any],
    max_frame_bytes: int | None = None,
) -> bytes:
    result, failure = _capture_protocol_call(lambda: _encode_frame(message, max_frame_bytes))
    message = b""
    max_frame_bytes = None
    if failure is not None:
        safe_error = ProtocolError(failure.code, failure.request_id)
        failure = None
        raise safe_error from None
    if not isinstance(result, bytes):
        result = None
        raise ProtocolError("operation_failed") from None
    return result


class FrameDecoder:
    """Incremental decoder for the protocol's transport-independent frame."""

    def __init__(self, max_frame_bytes: int | None = None) -> None:
        self._max_frame_bytes = _effective_frame_limit(max_frame_bytes)
        self._buffer = bytearray()
        self._expected_length: int | None = None
        self._single_frame = False
        self._require_frame = False
        self._frames_decoded = 0
        self._failed = False

    @classmethod
    def for_hello(cls) -> FrameDecoder:
        """Create the mandatory pre-negotiation, single-frame decoder."""

        decoder = cls(max_frame_bytes=int(CONTRACT["framing"]["max_hello_bytes"]))
        decoder._single_frame = True
        decoder._require_frame = True
        return decoder

    def _fail(self, code: str) -> None:
        self._buffer.clear()
        self._expected_length = None
        self._failed = True
        raise ProtocolError(code)

    def _feed(self, data: bytes) -> list[bytes]:
        if not isinstance(data, bytes):
            raise ProtocolError("request_invalid")
        if self._failed:
            raise ProtocolError("request_invalid")
        frames: list[bytes] = []
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            if self._single_frame and self._frames_decoded >= 1:
                self._fail("request_invalid")
            if self._expected_length is None:
                header_bytes = min(4 - len(self._buffer), len(view) - offset)
                self._buffer.extend(view[offset : offset + header_bytes])
                offset += header_bytes
                if len(self._buffer) != 4:
                    break
                declared = int.from_bytes(self._buffer, "big")
                self._buffer.clear()
                try:
                    validate_declared_length(declared, self._max_frame_bytes)
                except ProtocolError as error:
                    self._fail(error.code)
                self._expected_length = declared
            body_bytes = min(
                self._expected_length - len(self._buffer),
                len(view) - offset,
            )
            self._buffer.extend(view[offset : offset + body_bytes])
            offset += body_bytes
            if len(self._buffer) != self._expected_length:
                break
            frame = bytes(self._buffer)
            self._buffer.clear()
            self._expected_length = None
            frames.append(frame)
            self._frames_decoded += 1
        return frames

    def feed(self, data: bytes) -> list[bytes]:
        result, failure = _capture_protocol_call(lambda: self._feed(data))
        data = b""
        if failure is not None:
            self._buffer.clear()
            self._expected_length = None
            self._failed = True
            safe_error = ProtocolError(failure.code, failure.request_id)
            failure = None
            raise safe_error from None
        if not isinstance(result, list) or not all(isinstance(frame, bytes) for frame in result):
            self._buffer.clear()
            self._expected_length = None
            self._failed = True
            result = None
            raise ProtocolError("operation_failed") from None
        return result

    def finish(self) -> None:
        if (
            self._failed
            or self._expected_length is not None
            or self._buffer
            or (self._require_frame and self._frames_decoded != 1)
        ):
            self._fail("request_invalid")


def _exact_fields(
    value: dict[str, Any],
    expected: set[str],
    *,
    request_id: str | None = None,
) -> None:
    if set(value) != expected:
        raise ProtocolError("request_invalid", request_id)


def _request_id_from(value: dict[str, Any]) -> str | None:
    request_id = value.get("request_id")
    return request_id if _valid_id(request_id) else None


def _negotiate_hello(
    raw: bytes,
    *,
    authenticated_role: str,
    broker_product_version: str,
) -> HelloNegotiation:
    """Negotiate only after a future admission layer supplies a bound role."""

    message = parse_canonical_object(raw, max_bytes=int(CONTRACT["framing"]["max_hello_bytes"]))
    request_id = _request_id_from(message)
    _exact_fields(
        message,
        {
            "claimed_role",
            "client_product_version",
            "request_id",
            "supported_protocol_versions",
        },
        request_id=request_id,
    )
    if request_id is None:
        raise ProtocolError("request_invalid")
    claimed_role = message["claimed_role"]
    roles = CONTRACT["roles"]
    if not isinstance(claimed_role, str) or claimed_role not in roles:
        raise ProtocolError("broker_unauthorized", request_id)
    if (
        not isinstance(authenticated_role, str)
        or authenticated_role not in roles
        or authenticated_role != claimed_role
    ):
        raise ProtocolError("broker_unauthorized", request_id)
    if not _valid_product_version(message["client_product_version"]):
        raise ProtocolError("request_invalid", request_id)
    if not _valid_product_version(broker_product_version):
        raise ProtocolError("operation_failed", request_id)

    versions = message["supported_protocol_versions"]
    version_limit = int(CONTRACT["field_limits"]["supported_versions_count"])
    if (
        not isinstance(versions, list)
        or not 1 <= len(versions) <= version_limit
        or any(type(version) is not int or version <= 0 for version in versions)
        or any(left >= right for left, right in zip(versions, versions[1:]))
    ):
        raise ProtocolError("request_invalid", request_id)
    supported = set(CONTRACT["supported_protocol_versions"])
    common = [version for version in versions if version in supported]
    if not common:
        raise ProtocolError("broker_incompatible", request_id)
    selected = max(common)
    state = ConnectionState(
        _creation_token=_CONNECTION_STATE_TOKEN,
        role=authenticated_role,
        protocol_version=selected,
        seen_request_ids={request_id},
    )
    response = {
        "broker_product_version": broker_product_version,
        "broker_protocol_version": selected,
        "request_id": request_id,
        "role": authenticated_role,
    }
    return HelloNegotiation(state=state, response=response)


def negotiate_hello(
    raw: bytes,
    *,
    authenticated_role: str,
    broker_product_version: str,
) -> HelloNegotiation:
    result, failure = _capture_protocol_call(
        lambda: _negotiate_hello(
            raw,
            authenticated_role=authenticated_role,
            broker_product_version=broker_product_version,
        )
    )
    raw = b""
    authenticated_role = ""
    broker_product_version = ""
    if failure is not None:
        safe_error = ProtocolError(failure.code, failure.request_id)
        failure = None
        raise safe_error from None
    if not isinstance(result, HelloNegotiation):
        result = None
        raise ProtocolError("operation_failed") from None
    return result


def operation_allowed(role: object, operation: object) -> bool:
    if not isinstance(role, str) or not isinstance(operation, str):
        return False
    allowed = CONTRACT["roles"].get(role)
    return isinstance(allowed, list) and operation in allowed


def operation_replay(operation: object) -> str | None:
    if not isinstance(operation, str):
        return None
    spec = CONTRACT["operations"].get(operation)
    return spec.get("replay") if isinstance(spec, dict) else None


def deadline_ms(operation: object, *, remote_tner: bool) -> int | None:
    if not isinstance(operation, str) or type(remote_tner) is not bool:
        return None
    spec = CONTRACT["operations"].get(operation)
    if not isinstance(spec, dict):
        return None
    key = "deadline_remote_tner" if remote_tner else "deadline_local"
    profile = spec.get(key)
    if profile is None:
        return None
    deadline = CONTRACT["deadline_profiles_ms"].get(profile)
    return deadline if type(deadline) is int and deadline > 0 else None


def _message_limit(role: str, operation: str, *, response: bool) -> int | None:
    spec = CONTRACT["operations"].get(operation)
    if not isinstance(spec, dict) or role not in CONTRACT["roles"]:
        return None
    limit_name = spec["response_limit" if response else "request_limit"]
    framing = CONTRACT["framing"]
    limit = framing["max_frame_bytes"] if limit_name == "pdf" else framing["default_message_bytes"]
    if response and role == "extension":
        limit = min(limit, framing["extension_response_bytes"])
    return int(limit)


def _validate_opaque_id(value: object, request_id: str) -> None:
    if not _valid_id(value):
        raise ProtocolError("request_invalid", request_id)


def _uses_remote_tner_limit(spec: dict[str, Any], remote_tner: bool) -> bool:
    primary_scans = spec.get("remote_tner_primary_scans")
    return remote_tner and type(primary_scans) is int and primary_scans > 0


def _validate_text(value: object, *, remote_tner: bool, request_id: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or all(ord(char) in _BLANK_TEXT_CODE_POINTS for char in value)
    ):
        raise ProtocolError("request_invalid", request_id)
    limit_key = "remote_tner_text_chars" if remote_tner else "text_chars"
    if len(value) > int(CONTRACT["field_limits"][limit_key]):
        raise ProtocolError("payload_too_large", request_id)


def _validate_pdf_base64(value: object, request_id: str) -> None:
    if not isinstance(value, str) or not value:
        raise ProtocolError("request_invalid", request_id)
    if not value.isascii():
        raise ProtocolError("request_invalid", request_id)
    if len(value) > int(CONTRACT["framing"]["max_pdf_base64_bytes"]):
        raise ProtocolError("payload_too_large", request_id)
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error):
        raise ProtocolError("request_invalid", request_id) from None
    if len(decoded) > int(CONTRACT["framing"]["max_pdf_raw_bytes"]):
        decoded = b""
        raise ProtocolError("payload_too_large", request_id)
    canonical = base64.b64encode(decoded).decode("ascii")
    decoded = b""
    if canonical != value:
        canonical = ""
        raise ProtocolError("request_invalid", request_id)


def _decimal_parts(value: str) -> tuple[str, str]:
    integer, separator, fraction = value.partition(".")
    return integer, fraction if separator else ""


def _compare_decimals(left: str, right: str) -> int:
    left_integer, left_fraction = _decimal_parts(left)
    right_integer, right_fraction = _decimal_parts(right)
    if len(left_integer) != len(right_integer):
        return -1 if len(left_integer) < len(right_integer) else 1
    if left_integer != right_integer:
        return -1 if left_integer < right_integer else 1
    width = max(len(left_fraction), len(right_fraction))
    left_fraction = left_fraction.ljust(width, "0")
    right_fraction = right_fraction.ljust(width, "0")
    if left_fraction == right_fraction:
        return 0
    return -1 if left_fraction < right_fraction else 1


def _enum_contains(values: object, value: object) -> bool:
    return isinstance(values, list) and any(
        type(candidate) is type(value) and candidate == value for candidate in values
    )


def _validate_result_schema(
    value: object,
    schema: object,
    *,
    request_id: str,
    active_refs: frozenset[str] = frozenset(),
) -> None:
    """Validate one closed broker result shape from the shared policy."""

    if not isinstance(schema, dict):
        raise ProtocolError("operation_failed", request_id)
    if "ref" in schema:
        if set(schema) != {"ref"} or not isinstance(schema["ref"], str):
            raise ProtocolError("operation_failed", request_id)
        reference = schema["ref"]
        definitions = CONTRACT["result_schema_definitions"]
        resolved = definitions.get(reference)
        if not isinstance(resolved, dict) or reference in active_refs:
            raise ProtocolError("operation_failed", request_id)
        _validate_result_schema(
            value,
            resolved,
            request_id=request_id,
            active_refs=active_refs | {reference},
        )
        return

    kind = schema.get("kind")
    if kind == "boolean":
        if type(value) is not bool:
            raise ProtocolError("request_invalid", request_id)
        return
    if kind == "integer":
        if type(value) is not int:
            raise ProtocolError("request_invalid", request_id)
        minimum = schema.get("minimum", 0)
        maximum = schema.get("maximum", _JSON_INTEGER_MAX)
        if (
            type(minimum) is not int
            or type(maximum) is not int
            or minimum < 0
            or maximum > _JSON_INTEGER_MAX
            or minimum > maximum
        ):
            raise ProtocolError("operation_failed", request_id)
        if not minimum <= value <= maximum or (
            "enum" in schema and not _enum_contains(schema["enum"], value)
        ):
            raise ProtocolError("request_invalid", request_id)
        return
    if kind == "decimal":
        if not isinstance(value, str) or _DECIMAL_RE.fullmatch(value) is None:
            raise ProtocolError("request_invalid", request_id)
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None:
            if not isinstance(minimum, str) or _DECIMAL_RE.fullmatch(minimum) is None:
                raise ProtocolError("operation_failed", request_id)
            if _compare_decimals(value, minimum) < 0:
                raise ProtocolError("request_invalid", request_id)
        if maximum is not None:
            if not isinstance(maximum, str) or _DECIMAL_RE.fullmatch(maximum) is None:
                raise ProtocolError("operation_failed", request_id)
            if _compare_decimals(value, maximum) > 0:
                raise ProtocolError("request_invalid", request_id)
        return
    if kind == "string":
        if not isinstance(value, str):
            raise ProtocolError("request_invalid", request_id)
        minimum = schema.get("min_chars", 0)
        maximum = schema.get("max_chars")
        if (
            type(minimum) is not int
            or minimum < 0
            or (maximum is not None and (type(maximum) is not int or maximum < minimum))
        ):
            raise ProtocolError("operation_failed", request_id)
        if len(value) < minimum or (maximum is not None and len(value) > maximum):
            raise ProtocolError("request_invalid", request_id)
        if "enum" in schema and not _enum_contains(schema["enum"], value):
            raise ProtocolError("request_invalid", request_id)
        pattern = schema.get("pattern")
        if pattern == "opaque_id":
            valid_pattern = _valid_id(value)
        elif pattern == "data_type":
            valid_pattern = _DATA_TYPE_RE.fullmatch(value) is not None
        elif pattern == "provider":
            valid_pattern = _PROVIDER_RE.fullmatch(value) is not None
        elif pattern == "base64":
            try:
                decoded = base64.b64decode(value, validate=True)
            except (ValueError, base64.binascii.Error):
                raise ProtocolError("request_invalid", request_id) from None
            valid_pattern = base64.b64encode(decoded).decode("ascii") == value
            decoded = b""
        elif pattern is None:
            valid_pattern = True
        else:
            raise ProtocolError("operation_failed", request_id)
        if not valid_pattern:
            raise ProtocolError("request_invalid", request_id)
        return
    if kind == "object":
        fields = schema.get("fields")
        if not isinstance(value, dict) or not isinstance(fields, dict):
            code = "request_invalid" if not isinstance(value, dict) else "operation_failed"
            raise ProtocolError(code, request_id)
        if set(value) != set(fields):
            raise ProtocolError("request_invalid", request_id)
        for field, field_schema in fields.items():
            _validate_result_schema(
                value[field],
                field_schema,
                request_id=request_id,
                active_refs=active_refs,
            )
        return
    if kind == "map":
        values_schema = schema.get("values")
        if not isinstance(value, dict):
            raise ProtocolError("request_invalid", request_id)
        if not isinstance(values_schema, dict):
            raise ProtocolError("operation_failed", request_id)
        key_pattern = schema.get("key_pattern")
        for key, item in value.items():
            if (
                key_pattern != "data_type"
                or not isinstance(key, str)
                or _DATA_TYPE_RE.fullmatch(key) is None
            ):
                if key_pattern != "data_type":
                    raise ProtocolError("operation_failed", request_id)
                raise ProtocolError("request_invalid", request_id)
            _validate_result_schema(
                item,
                values_schema,
                request_id=request_id,
                active_refs=active_refs,
            )
        return
    if kind == "array":
        items_schema = schema.get("items")
        if not isinstance(value, list):
            raise ProtocolError("request_invalid", request_id)
        if not isinstance(items_schema, dict):
            raise ProtocolError("operation_failed", request_id)
        minimum = schema.get("min_items", 0)
        maximum = schema.get("max_items")
        if (
            type(minimum) is not int
            or minimum < 0
            or (maximum is not None and (type(maximum) is not int or maximum < minimum))
        ):
            raise ProtocolError("operation_failed", request_id)
        if len(value) < minimum or (maximum is not None and len(value) > maximum):
            raise ProtocolError("request_invalid", request_id)
        for item in value:
            _validate_result_schema(
                item,
                items_schema,
                request_id=request_id,
                active_refs=active_refs,
            )
        ordered_values = schema.get("ordered_values")
        if ordered_values is not None:
            if not isinstance(ordered_values, list):
                raise ProtocolError("operation_failed", request_id)
            indexes: list[int] = []
            for item in value:
                try:
                    indexes.append(ordered_values.index(item))
                except ValueError:
                    raise ProtocolError("operation_failed", request_id) from None
            if indexes != sorted(set(indexes)):
                raise ProtocolError("request_invalid", request_id)
        return
    if kind == "nullable":
        nested = schema.get("schema")
        if not isinstance(nested, dict):
            raise ProtocolError("operation_failed", request_id)
        if value is not None:
            _validate_result_schema(
                value,
                nested,
                request_id=request_id,
                active_refs=active_refs,
            )
        return
    if kind == "one_of":
        variants = schema.get("variants")
        if not isinstance(variants, list) or not variants:
            raise ProtocolError("operation_failed", request_id)
        matches = 0
        for variant in variants:
            try:
                _validate_result_schema(
                    value,
                    variant,
                    request_id=request_id,
                    active_refs=active_refs,
                )
            except ProtocolError as error:
                if error.code == "operation_failed":
                    raise
            else:
                matches += 1
        if matches != 1:
            raise ProtocolError("request_invalid", request_id)
        return
    raise ProtocolError("operation_failed", request_id)


def _validate_payload_field(
    kind: str,
    value: object,
    *,
    role: str,
    request_id: str,
    remote_tner: bool,
) -> None:
    if kind == "text":
        _validate_text(value, remote_tner=remote_tner, request_id=request_id)
    elif kind == "mode":
        if not isinstance(value, str) or value not in {"token", "surrogate"}:
            raise ProtocolError("request_invalid", request_id)
    elif kind == "opaque_id":
        _validate_opaque_id(value, request_id)
    elif kind == "provider_name":
        if not isinstance(value, str) or _PROVIDER_RE.fullmatch(value) is None:
            raise ProtocolError("request_invalid", request_id)
    elif kind == "role_scope_kind":
        allowed = CONTRACT["scope_kinds"].get(role)
        if not isinstance(value, str) or not isinstance(allowed, list) or value not in allowed:
            raise ProtocolError("broker_unauthorized", request_id)
    elif kind == "pdf_base64":
        _validate_pdf_base64(value, request_id)
    elif kind == "audit_limit":
        limits = CONTRACT["field_limits"]
        if (
            type(value) is not int
            or not limits["audit_limit_min"] <= value <= limits["audit_limit_max"]
        ):
            raise ProtocolError("request_invalid", request_id)
    elif kind == "audit_offset":
        if type(value) is not int or not 0 <= value <= CONTRACT["field_limits"]["audit_offset_max"]:
            raise ProtocolError("request_invalid", request_id)
    else:
        raise ProtocolError("operation_failed", request_id)


def _validate_request(
    raw: bytes,
    *,
    state: ConnectionState,
    remote_tner: bool,
) -> BrokerRequest:
    """Validate one request without dispatching, retaining, or replaying it."""

    if (
        not isinstance(state, ConnectionState)
        or not isinstance(state.role, str)
        or state.role not in CONTRACT["roles"]
        or state.protocol_version not in CONTRACT["supported_protocol_versions"]
        or type(remote_tner) is not bool
    ):
        raise ProtocolError("broker_unauthorized")
    if state.terminal:
        raise ProtocolError(CONTRACT["connection_policy"]["terminal_error"])
    if not state._admit_message():
        raise ProtocolError(CONTRACT["connection_policy"]["message_limit_error"])
    initial_limit = (
        CONTRACT["framing"]["max_frame_bytes"]
        if state.role == "desktop"
        else CONTRACT["framing"]["default_message_bytes"]
    )
    message = parse_canonical_object(raw, max_bytes=int(initial_limit))
    request_id = _request_id_from(message)
    if request_id is None:
        raise ProtocolError("request_invalid")
    if state._has_request_id(request_id):
        raise ProtocolError("request_invalid", request_id)
    state._record_request_id(request_id)
    operation = message.get("operation")
    if not isinstance(operation, str) or _OPERATION_RE.fullmatch(operation) is None:
        raise ProtocolError("request_invalid", request_id)
    spec = CONTRACT["operations"].get(operation)
    if not isinstance(spec, dict):
        raise ProtocolError("request_invalid", request_id)
    if not operation_allowed(state.role, operation):
        raise ProtocolError("broker_unauthorized", request_id)

    scope_rule = spec["scope"]
    expected = {"broker_protocol_version", "operation", "payload", "request_id"}
    if scope_rule == "required":
        expected.add("scope_id")
    _exact_fields(message, expected, request_id=request_id)
    version = message["broker_protocol_version"]
    if type(version) is not int or version != state.protocol_version:
        raise ProtocolError("broker_incompatible", request_id)
    scope_id = message.get("scope_id")
    if scope_rule == "required":
        _validate_opaque_id(scope_id, request_id)
    elif scope_id is not None:
        raise ProtocolError("request_invalid", request_id)

    request_limit = _message_limit(state.role, operation, response=False)
    if request_limit is None:
        raise ProtocolError("operation_failed", request_id)
    if len(raw) > request_limit:
        raise ProtocolError("payload_too_large", request_id)
    selected_deadline = deadline_ms(operation, remote_tner=remote_tner)
    if selected_deadline is None:
        code = (
            CONTRACT["remote_tner_policy"]["unsupported_operation_error"]
            if remote_tner
            else "request_invalid"
        )
        raise ProtocolError(code, request_id)
    remote_tner_max_calls = int(spec["remote_tner_max_calls"]) if remote_tner else 0
    local_detection_phases = spec["local_detection_phases"] if not remote_tner else None

    payload = message["payload"]
    if not isinstance(payload, dict):
        raise ProtocolError("request_invalid", request_id)
    required = spec["payload_required"]
    optional = spec["payload_optional"]
    if not isinstance(required, dict) or not isinstance(optional, dict):
        raise ProtocolError("operation_failed", request_id)
    if set(payload) != set(required) | (set(payload) & set(optional)):
        raise ProtocolError("request_invalid", request_id)
    if not set(required) <= set(payload):
        raise ProtocolError("request_invalid", request_id)
    tner_text_limit = _uses_remote_tner_limit(spec, remote_tner)
    for field, value in payload.items():
        kind = required.get(field, optional.get(field))
        if not isinstance(kind, str):
            raise ProtocolError("request_invalid", request_id)
        _validate_payload_field(
            kind,
            value,
            role=state.role,
            request_id=request_id,
            remote_tner=tner_text_limit,
        )

    return BrokerRequest(
        protocol_version=state.protocol_version,
        request_id=request_id,
        operation=operation,
        scope_id=scope_id,
        payload=payload,
        deadline_ms=selected_deadline,
        local_detection_phases=local_detection_phases,
        local_intermediate_text_chars=(
            int(CONTRACT["field_limits"]["local_intermediate_text_chars"])
            if type(local_detection_phases) is int and local_detection_phases > 0
            else None
        ),
        remote_tner_max_calls=remote_tner_max_calls,
        remote_tner_text_chars=(
            int(CONTRACT["field_limits"]["remote_tner_text_chars"])
            if remote_tner and remote_tner_max_calls
            else None
        ),
        replay=spec["replay"],
        uncertain_completion=spec["uncertain_completion"],
    )


def validate_request(
    raw: bytes,
    *,
    state: ConnectionState,
    remote_tner: bool,
) -> BrokerRequest:
    result, failure = _capture_protocol_call(
        lambda: _validate_request(raw, state=state, remote_tner=remote_tner)
    )
    raw = b""
    state = None  # type: ignore[assignment]
    remote_tner = False
    if failure is not None:
        safe_error = ProtocolError(failure.code, failure.request_id)
        failure = None
        raise safe_error from None
    if not isinstance(result, BrokerRequest):
        result = None
        raise ProtocolError("operation_failed") from None
    return result


def error_message(
    code: object,
    *,
    request_id: str | None,
    protocol_version: int = 1,
) -> dict[str, Any]:
    """Build one fixed error; callers cannot provide retry metadata."""

    safe_code = safe_error_code(code)
    safe_request_id = request_id if _valid_id(request_id) else None
    if (
        type(protocol_version) is not int
        or protocol_version not in CONTRACT["supported_protocol_versions"]
    ):
        protocol_version = 1
    return {
        "broker_protocol_version": protocol_version,
        "error": {
            "code": safe_code,
            "retry": CONTRACT["errors"][safe_code]["retry"],
        },
        "request_id": safe_request_id,
    }


def _success_message(
    operation: str,
    *,
    request_id: str,
    result: dict[str, Any],
    role: str,
    protocol_version: int = 1,
) -> dict[str, Any]:
    """Build a strict success envelope after operation-result validation."""

    if not operation_allowed(role, operation) or not _valid_id(request_id):
        raise ProtocolError("broker_unauthorized")
    if (
        type(protocol_version) is not int
        or protocol_version not in CONTRACT["supported_protocol_versions"]
    ):
        raise ProtocolError("operation_failed", request_id)
    spec = CONTRACT["operations"][operation]
    message = {
        "broker_protocol_version": protocol_version,
        "request_id": request_id,
        "result": result,
    }
    encoded = canonical_json_bytes(message)
    limit = _message_limit(role, operation, response=True)
    if limit is None or len(encoded) > limit:
        raise ProtocolError("payload_too_large", request_id)
    _validate_result_schema(
        result,
        spec.get("result_schema"),
        request_id=request_id,
    )
    return message


def success_message(
    operation: str,
    *,
    request_id: str,
    result: dict[str, Any],
    role: str,
    protocol_version: int = 1,
) -> dict[str, Any]:
    message, failure = _capture_protocol_call(
        lambda: _success_message(
            operation,
            request_id=request_id,
            result=result,
            role=role,
            protocol_version=protocol_version,
        )
    )
    operation = ""
    request_id = ""
    result = {}
    role = ""
    protocol_version = 1
    if failure is not None:
        safe_error = ProtocolError(failure.code, failure.request_id)
        failure = None
        raise safe_error from None
    if not isinstance(message, dict):
        message = None
        raise ProtocolError("operation_failed") from None
    return message


def _validate_response(
    raw: bytes,
    *,
    role: str,
    operation: str,
    request_id: str,
) -> dict[str, Any]:
    """Validate a correlated success or fixed error with no passthrough fields."""

    if not operation_allowed(role, operation) or not _valid_id(request_id):
        raise ProtocolError("broker_unauthorized")
    limit = _message_limit(role, operation, response=True)
    if limit is None:
        raise ProtocolError("operation_failed", request_id)
    message = parse_canonical_object(raw, max_bytes=limit)
    if (
        type(message.get("broker_protocol_version")) is not int
        or message.get("broker_protocol_version") != 1
        or message.get("request_id") != request_id
    ):
        raise ProtocolError("request_invalid", request_id)
    has_result = "result" in message
    has_error = "error" in message
    if has_result == has_error:
        raise ProtocolError("request_invalid", request_id)
    if has_result:
        _exact_fields(
            message,
            {"broker_protocol_version", "request_id", "result"},
            request_id=request_id,
        )
        _validate_result_schema(
            message["result"],
            CONTRACT["operations"][operation].get("result_schema"),
            request_id=request_id,
        )
        return message

    _exact_fields(
        message,
        {"broker_protocol_version", "error", "request_id"},
        request_id=request_id,
    )
    error = message["error"]
    if not isinstance(error, dict) or set(error) != {"code", "retry"}:
        raise ProtocolError("request_invalid", request_id)
    code = error["code"]
    spec = CONTRACT["errors"].get(code) if isinstance(code, str) else None
    if not isinstance(spec, dict) or error["retry"] != spec["retry"]:
        raise ProtocolError("request_invalid", request_id)
    return message


def validate_response(
    raw: bytes,
    *,
    role: str,
    operation: str,
    request_id: str,
) -> dict[str, Any]:
    message, failure = _capture_protocol_call(
        lambda: _validate_response(
            raw,
            role=role,
            operation=operation,
            request_id=request_id,
        )
    )
    raw = b""
    role = ""
    operation = ""
    request_id = ""
    if failure is not None:
        safe_error = ProtocolError(failure.code, failure.request_id)
        failure = None
        raise safe_error from None
    if not isinstance(message, dict):
        message = None
        raise ProtocolError("operation_failed") from None
    return message


__all__ = [
    "CONTRACT",
    "CONTRACT_PATH",
    "BrokerRequest",
    "ConnectionState",
    "FrameDecoder",
    "HelloNegotiation",
    "ProtocolError",
    "canonical_json_bytes",
    "deadline_ms",
    "encode_frame",
    "error_message",
    "negotiate_hello",
    "operation_allowed",
    "operation_replay",
    "parse_canonical_object",
    "safe_error_code",
    "success_message",
    "validate_declared_length",
    "validate_request",
    "validate_response",
]
