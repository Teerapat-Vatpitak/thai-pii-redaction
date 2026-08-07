use std::path::PathBuf;

use aiguard_native_broker_protocol::{
    canonical_json_bytes, deadline_ms, encode_frame, error_message, negotiate_hello,
    operation_allowed, operation_replay, parse_canonical_object, safe_error_code,
    validate_declared_length, validate_request, validate_response, ConnectionState, FrameDecoder,
    ProtocolError,
};
use serde_json::Value;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("crate has repository parent")
        .to_path_buf()
}

fn fixtures() -> Value {
    let path = root().join("tests/fixtures/native_broker/v1/conformance.json");
    serde_json::from_slice(&std::fs::read(path).expect("read conformance fixtures"))
        .expect("parse conformance fixtures")
}

fn contract_file() -> Value {
    let path = root().join("native-broker/protocol-v1.json");
    serde_json::from_slice(&std::fs::read(path).expect("read contract")).expect("parse contract")
}

fn state(role: &str) -> ConnectionState {
    let hello = serde_json::json!({
        "claimed_role": role,
        "client_product_version": "9.9.9-test",
        "request_id": format!("hello-{role}"),
        "supported_protocol_versions": [1],
    });
    negotiate_hello(&canonical_json_bytes(&hello).unwrap(), role, "8.8.8-test")
        .unwrap()
        .state
}

#[test]
fn embedded_contract_is_the_authoritative_policy_file() {
    assert_eq!(fixtures()["fixture_schema_version"], 1);
    let embedded: Value =
        serde_json::from_str(aiguard_native_broker_protocol::CONTRACT_JSON).unwrap();
    assert_eq!(embedded, contract_file());
    assert_eq!(embedded["contract_schema_version"], 1);
    assert_eq!(
        embedded["supported_protocol_versions"],
        serde_json::json!([1])
    );
    assert!(embedded["roles"].get("backend").is_none());
}

#[test]
fn shared_hello_vectors_negotiate_or_fail_exactly() {
    let fixtures = fixtures();
    for vector in fixtures["hello_vectors"].as_array().unwrap() {
        let raw = vector["json"].as_str().unwrap().as_bytes();
        let result = negotiate_hello(
            raw,
            vector["admitted_role"].as_str().unwrap(),
            vector
                .get("broker_product_version")
                .and_then(Value::as_str)
                .unwrap_or("8.8.8-test"),
        );
        if let Some(code) = vector.get("expect_error").and_then(Value::as_str) {
            assert_eq!(result.unwrap_err().code(), code, "{}", vector["name"]);
        } else {
            let negotiated = result.unwrap();
            assert_eq!(
                negotiated.state.protocol_version(),
                vector["expect_selected_version"].as_u64().unwrap()
            );
            assert_eq!(
                negotiated.state.role(),
                vector["admitted_role"].as_str().unwrap()
            );
            if let Some(expected) = vector.get("expect_response_json").and_then(Value::as_str) {
                assert_eq!(
                    String::from_utf8(canonical_json_bytes(&negotiated.response).unwrap()).unwrap(),
                    expected
                );
            }
        }
    }
}

#[test]
fn hello_is_mandatory_first_and_cannot_repeat() {
    let fixtures = fixtures();
    let request = fixtures["request_vectors"][0]["json"].as_str().unwrap();
    assert_eq!(
        negotiate_hello(request.as_bytes(), "desktop", "8.8.8-test")
            .unwrap_err()
            .code(),
        "request_invalid"
    );

    let hello = fixtures["hello_vectors"][0]["json"].as_str().unwrap();
    let mut connection = state("desktop");
    assert_eq!(
        validate_request(hello.as_bytes(), &mut connection, false)
            .unwrap_err()
            .code(),
        "request_invalid"
    );
}

#[test]
fn authoritative_message_frames_are_exact_bytes() {
    let fixtures = fixtures();
    let vectors = [
        &fixtures["hello_vectors"][0],
        &fixtures["request_vectors"][0],
        &fixtures["response_vectors"][0],
    ];
    for vector in vectors {
        let actual = encode_frame(vector["json"].as_str().unwrap().as_bytes(), None).unwrap();
        assert_eq!(hex::encode(actual), vector["frame_hex"].as_str().unwrap());
    }
}

#[test]
fn hello_decoder_is_capped_single_frame_and_switches_after_negotiation() {
    let fixtures = fixtures();
    let hello = hex::decode(fixtures["hello_vectors"][0]["frame_hex"].as_str().unwrap()).unwrap();
    let request = hex::decode(
        fixtures["request_vectors"][0]["frame_hex"]
            .as_str()
            .unwrap(),
    )
    .unwrap();
    let mut hello_decoder = FrameDecoder::for_hello().unwrap();
    assert_eq!(
        hello_decoder.feed(&hello).unwrap(),
        vec![hello[4..].to_vec()]
    );
    hello_decoder.finish().unwrap();

    let mut request_decoder = FrameDecoder::new(None).unwrap();
    assert_eq!(
        request_decoder.feed(&request).unwrap(),
        vec![request[4..].to_vec()]
    );
    request_decoder.finish().unwrap();

    let mut pipelined = FrameDecoder::for_hello().unwrap();
    assert_eq!(
        pipelined
            .feed(
                &hello
                    .iter()
                    .chain(request.iter())
                    .copied()
                    .collect::<Vec<_>>()
            )
            .unwrap_err()
            .code(),
        "request_invalid"
    );
}

#[test]
fn post_hello_decoder_handles_partial_and_multiple_frames() {
    let fixtures = fixtures();
    let request = hex::decode(
        fixtures["request_vectors"][0]["frame_hex"]
            .as_str()
            .unwrap(),
    )
    .unwrap();
    let response = hex::decode(
        fixtures["response_vectors"][0]["frame_hex"]
            .as_str()
            .unwrap(),
    )
    .unwrap();
    let mut decoder = FrameDecoder::new(None).unwrap();
    let mut decoded = Vec::new();
    for byte in request.iter().chain(response.iter()) {
        decoded.extend(decoder.feed(&[*byte]).unwrap());
    }
    decoder.finish().unwrap();
    assert_eq!(decoded, vec![request[4..].to_vec(), response[4..].to_vec()]);
}

#[test]
fn pre_hello_frame_limit_is_shared_and_rejects_before_body_copy() {
    let fixtures = fixtures();
    for vector in fixtures["hello_frame_vectors"].as_array().unwrap() {
        let mut decoder = FrameDecoder::for_hello().unwrap();
        let mut bytes = (vector["declared_length"].as_u64().unwrap() as u32)
            .to_be_bytes()
            .to_vec();
        if let Some(attached) = vector.get("attached_body_hex").and_then(Value::as_str) {
            bytes.extend(hex::decode(attached).unwrap());
        }
        if vector["valid"].as_bool().unwrap() {
            assert!(decoder.feed(&bytes).unwrap().is_empty());
            assert_eq!(decoder.finish().unwrap_err().code(), "request_invalid");
        } else {
            assert_eq!(
                decoder.feed(&bytes).unwrap_err().code(),
                vector["expect_error"].as_str().unwrap()
            );
            assert_eq!(vector["expect_max_buffer_growth_bytes"].as_u64(), Some(4));
        }
    }
}

#[test]
fn frame_length_and_partial_vectors_are_shared() {
    let fixtures = fixtures();
    for vector in fixtures["frame_length_vectors"].as_array().unwrap() {
        let result = validate_declared_length(vector["declared_length"].as_u64().unwrap(), None);
        if vector["valid"].as_bool().unwrap() {
            result.unwrap();
        } else {
            assert_eq!(
                result.unwrap_err().code(),
                vector["expect_error"].as_str().unwrap()
            );
        }
    }
    for vector in fixtures["partial_frame_vectors"].as_array().unwrap() {
        let max = vector.get("max_frame_bytes").and_then(Value::as_u64);
        let mut decoder = FrameDecoder::new(max).unwrap();
        let bytes = hex::decode(vector["hex"].as_str().unwrap()).unwrap();
        if let Some(code) = vector.get("expect_error").and_then(Value::as_str) {
            assert_eq!(decoder.feed(&bytes).unwrap_err().code(), code);
        } else {
            assert!(decoder.feed(&bytes).unwrap().is_empty());
            assert_eq!(
                decoder.finish().unwrap_err().code(),
                vector["expect_error_at_eof"].as_str().unwrap()
            );
        }
    }
}

#[test]
fn invalid_decoder_limits_are_shared() {
    let fixtures = fixtures();
    for vector in fixtures["invalid_decoder_limits"].as_array().unwrap() {
        let error = FrameDecoder::new(vector["max_frame_bytes"].as_u64()).unwrap_err();
        assert_eq!(error.code(), vector["expect_error"].as_str().unwrap());
    }
}

#[test]
fn shared_request_vectors_enforce_role_scope_payload_and_version() {
    let fixtures = fixtures();
    for vector in fixtures["request_vectors"].as_array().unwrap() {
        let mut connection = state(vector["role"].as_str().unwrap());
        let result = validate_request(
            vector["json"].as_str().unwrap().as_bytes(),
            &mut connection,
            vector["remote_tner"].as_bool().unwrap(),
        );
        if let Some(code) = vector.get("expect_error").and_then(Value::as_str) {
            assert_eq!(result.unwrap_err().code(), code, "{}", vector["name"]);
        } else {
            let request = result.unwrap();
            assert_eq!(request.operation, vector["operation"]);
            assert_eq!(
                request.deadline_ms,
                deadline_ms(
                    vector["operation"].as_str().unwrap(),
                    vector["remote_tner"].as_bool().unwrap()
                )
            );
        }
    }
}

#[test]
fn request_id_is_single_use() {
    let fixtures = fixtures();
    let vector = &fixtures["request_vectors"][0];
    let mut connection = state("desktop");
    validate_request(
        vector["json"].as_str().unwrap().as_bytes(),
        &mut connection,
        false,
    )
    .unwrap();
    assert_eq!(
        validate_request(
            vector["json"].as_str().unwrap().as_bytes(),
            &mut connection,
            false
        )
        .unwrap_err()
        .code(),
        "request_invalid"
    );
}

#[test]
fn connection_message_limit_is_terminal_and_bounds_duplicate_work() {
    let fixtures = fixtures();
    let limit = fixtures["field_boundary_vectors"]
        .as_array()
        .unwrap()
        .iter()
        .find(|vector| vector["field"] == "connection_messages")
        .unwrap()["limit"]
        .as_u64()
        .unwrap();
    let mut connection = state("desktop");
    for index in 1..limit - 1 {
        let message = serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "broker_health",
            "payload": {},
            "request_id": format!("bounded-{index}"),
        });
        validate_request(
            &canonical_json_bytes(&message).unwrap(),
            &mut connection,
            false,
        )
        .unwrap();
    }
    assert_eq!(
        validate_request(b"{}", &mut connection, false)
            .unwrap_err()
            .code(),
        "request_invalid"
    );
    let duplicate_at_limit = canonical_json_bytes(&serde_json::json!({
        "broker_protocol_version": 1,
        "operation": "broker_health",
        "payload": {},
        "request_id": "bounded-1",
    }))
    .unwrap();
    assert_eq!(
        validate_request(&duplicate_at_limit, &mut connection, false)
            .unwrap_err()
            .code(),
        "broker_busy"
    );
    let over_limit = canonical_json_bytes(&serde_json::json!({
        "broker_protocol_version": 1,
        "operation": "broker_health",
        "payload": {},
        "request_id": "bounded-over-limit",
    }))
    .unwrap();
    assert_eq!(
        validate_request(&over_limit, &mut connection, false)
            .unwrap_err()
            .code(),
        "broker_unavailable"
    );
}

#[test]
fn rejected_requests_consume_valid_request_ids() {
    let fixtures = fixtures();
    for vector in fixtures["request_id_sequence_vectors"].as_array().unwrap() {
        let mut connection = state(vector["role"].as_str().unwrap());
        let first = validate_request(
            vector["first_json"].as_str().unwrap().as_bytes(),
            &mut connection,
            vector["remote_tner"].as_bool().unwrap(),
        )
        .unwrap_err();
        assert_eq!(first.code(), vector["first_error"].as_str().unwrap());

        let second = validate_request(
            vector["second_json"].as_str().unwrap().as_bytes(),
            &mut connection,
            vector["remote_tner"].as_bool().unwrap(),
        )
        .unwrap_err();
        assert_eq!(second.code(), vector["second_error"].as_str().unwrap());
    }
}

#[test]
fn shared_response_and_fixed_error_vectors_are_exact() {
    let fixtures = fixtures();
    for vector in fixtures["response_vectors"].as_array().unwrap() {
        let result = validate_response(
            vector["json"].as_str().unwrap().as_bytes(),
            vector["role"].as_str().unwrap(),
            vector["operation"].as_str().unwrap(),
            vector["request_id"].as_str().unwrap(),
        );
        if let Some(code) = vector.get("expect_error").and_then(Value::as_str) {
            assert_eq!(result.unwrap_err().code(), code);
        } else {
            result.unwrap();
        }
    }

    for vector in fixtures["success_builder_vectors"].as_array().unwrap() {
        let result = aiguard_native_broker_protocol::success_message(
            vector["operation"].as_str().unwrap(),
            vector["request_id"].as_str().unwrap(),
            vector["result"].clone(),
            vector["role"].as_str().unwrap(),
            vector["protocol_version"].as_u64().unwrap(),
        );
        if let Some(code) = vector.get("expect_error").and_then(Value::as_str) {
            assert_eq!(result.unwrap_err().code(), code);
        } else {
            assert_eq!(
                String::from_utf8(canonical_json_bytes(&result.unwrap()).unwrap()).unwrap(),
                vector["expect_json"]
            );
        }
    }

    let result_vectors = fixtures["result_schema_vectors"].as_array().unwrap();
    let covered: std::collections::BTreeSet<&str> = result_vectors
        .iter()
        .map(|vector| vector["operation"].as_str().unwrap())
        .collect();
    let policy = contract_file();
    let expected: std::collections::BTreeSet<&str> = policy["operations"]
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect();
    assert_eq!(covered, expected);
    for vector in result_vectors {
        let message = aiguard_native_broker_protocol::success_message(
            vector["operation"].as_str().unwrap(),
            vector["request_id"].as_str().unwrap(),
            vector["result"].clone(),
            vector["role"].as_str().unwrap(),
            1,
        )
        .unwrap();
        let raw = canonical_json_bytes(&message).unwrap();
        assert_eq!(
            validate_response(
                &raw,
                vector["role"].as_str().unwrap(),
                vector["operation"].as_str().unwrap(),
                vector["request_id"].as_str().unwrap(),
            )
            .unwrap(),
            message
        );
    }

    for vector in fixtures["result_mutation_vectors"].as_array().unwrap() {
        let source = result_vectors
            .iter()
            .find(|source| source["operation"] == vector["operation"])
            .unwrap();
        let mut result = source["result"].clone();
        let path = vector["path"].as_array().unwrap();
        let mut target = &mut result;
        for segment in &path[..path.len() - 1] {
            target = target
                .get_mut(segment.as_str().unwrap())
                .expect("shared mutation path");
        }
        target[path.last().unwrap().as_str().unwrap()] = vector["value"].clone();
        let error = aiguard_native_broker_protocol::success_message(
            vector["operation"].as_str().unwrap(),
            "result-mutation",
            result,
            source["role"].as_str().unwrap(),
            1,
        )
        .unwrap_err();
        assert_eq!(error.code(), vector["expect_error"].as_str().unwrap());
    }

    for vector in fixtures["error_messages"].as_array().unwrap() {
        let message = error_message(vector["code"].as_str().unwrap(), Some("error-1"), 1).unwrap();
        assert_eq!(
            String::from_utf8(canonical_json_bytes(&message).unwrap()).unwrap(),
            vector["json"]
        );
        validate_response(
            vector["json"].as_str().unwrap().as_bytes(),
            "desktop",
            "broker_health",
            "error-1",
        )
        .unwrap();
    }
    for vector in fixtures["uncorrelated_error_vectors"].as_array().unwrap() {
        let message = error_message(vector["code"].as_str().unwrap(), None, 1).unwrap();
        assert_eq!(
            String::from_utf8(canonical_json_bytes(&message).unwrap()).unwrap(),
            vector["json"]
        );
    }
}

#[test]
fn policy_deadline_and_replay_tables_match_shared_vectors() {
    let fixtures = fixtures();
    let policy = &fixtures["role_operation_policy"];
    let contract = contract_file();
    let operations: std::collections::BTreeSet<&str> = policy["operations"]
        .as_array()
        .unwrap()
        .iter()
        .map(|operation| operation.as_str().unwrap())
        .collect();
    let contract_operations: std::collections::BTreeSet<&str> = contract["operations"]
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect();
    assert_eq!(operations, contract_operations);
    let roles: std::collections::BTreeSet<&str> = policy["allowlists"]
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect();
    let contract_roles: std::collections::BTreeSet<&str> = contract["roles"]
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect();
    assert_eq!(roles, contract_roles);

    for (role, allowed) in policy["allowlists"].as_object().unwrap() {
        for operation in policy["operations"].as_array().unwrap() {
            let operation = operation.as_str().unwrap();
            assert_eq!(
                operation_allowed(role, operation),
                allowed
                    .as_array()
                    .unwrap()
                    .iter()
                    .any(|allowed| allowed.as_str() == Some(operation))
            );
        }
    }
    for role in policy["unknown_roles"].as_array().unwrap() {
        for operation in policy["operations"].as_array().unwrap() {
            assert!(!operation_allowed(
                role.as_str().unwrap(),
                operation.as_str().unwrap()
            ));
        }
    }
    for role in policy["allowlists"].as_object().unwrap().keys() {
        for operation in policy["unknown_operations"].as_array().unwrap() {
            assert!(!operation_allowed(role, operation.as_str().unwrap()));
        }
    }
    for vector in fixtures["deadline_vectors"].as_array().unwrap() {
        assert_eq!(
            deadline_ms(
                vector["operation"].as_str().unwrap(),
                vector["remote_tner"].as_bool().unwrap()
            ),
            vector["deadline_ms"].as_u64()
        );
    }
    let budget_vectors = fixtures["remote_tner_budget_vectors"].as_array().unwrap();
    let budget_operations: std::collections::BTreeSet<&str> = budget_vectors
        .iter()
        .map(|vector| vector["operation"].as_str().unwrap())
        .collect();
    assert_eq!(budget_operations, contract_operations);
    let source_only_operations: std::collections::BTreeSet<&str> = budget_vectors
        .iter()
        .filter(|vector| {
            vector["primary_scans"]
                .as_u64()
                .is_some_and(|scans| scans > 0)
        })
        .map(|vector| vector["operation"].as_str().unwrap())
        .collect();
    let disabled_operations: std::collections::BTreeSet<&str> = budget_vectors
        .iter()
        .filter(|vector| vector["deadline_ms"].is_null())
        .map(|vector| vector["operation"].as_str().unwrap())
        .collect();
    assert_eq!(
        source_only_operations,
        contract["remote_tner_policy"]["source_only_operations"]
            .as_array()
            .unwrap()
            .iter()
            .map(|operation| operation.as_str().unwrap())
            .collect::<std::collections::BTreeSet<_>>()
    );
    assert_eq!(
        disabled_operations,
        contract["remote_tner_policy"]["disabled_operations"]
            .as_array()
            .unwrap()
            .iter()
            .map(|operation| operation.as_str().unwrap())
            .collect::<std::collections::BTreeSet<_>>()
    );
    let calls_per_scan = contract["field_limits"]["remote_tner_calls_per_scan"]
        .as_u64()
        .unwrap();
    for vector in budget_vectors {
        let operation = vector["operation"].as_str().unwrap();
        let spec = &contract["operations"][operation];
        assert_eq!(spec["remote_tner_primary_scans"], vector["primary_scans"]);
        assert_eq!(spec["remote_tner_max_calls"], vector["max_calls"]);
        assert_eq!(deadline_ms(operation, true), vector["deadline_ms"].as_u64());
        if let Some(primary_scans) = vector["primary_scans"].as_u64() {
            assert_eq!(
                vector["max_calls"].as_u64(),
                Some(primary_scans * calls_per_scan)
            );
        }
    }
    let local_phase_vectors = fixtures["local_detection_phase_vectors"]
        .as_array()
        .unwrap();
    let local_phase_operations: std::collections::BTreeSet<&str> = local_phase_vectors
        .iter()
        .map(|vector| vector["operation"].as_str().unwrap())
        .collect();
    assert_eq!(local_phase_operations, contract_operations);
    for vector in local_phase_vectors {
        let operation = vector["operation"].as_str().unwrap();
        assert_eq!(
            contract["operations"][operation]["local_detection_phases"],
            vector["phases"]
        );
        assert_eq!(
            deadline_ms(operation, false),
            vector["deadline_ms"].as_u64()
        );
    }
    let mutation_vectors = fixtures["replay_and_mutation_vectors"].as_array().unwrap();
    let mutation_operations: std::collections::BTreeSet<&str> = mutation_vectors
        .iter()
        .map(|vector| vector["operation"].as_str().unwrap())
        .collect();
    assert_eq!(mutation_operations, contract_operations);
    for vector in mutation_vectors {
        let operation = vector["operation"].as_str().unwrap();
        assert_eq!(operation_replay(operation), vector["replay"].as_str());
        assert_eq!(
            contract["operations"][operation]["uncertain_completion"],
            vector["uncertain_completion"]
        );
    }
    for (index, session_id) in [None, Some("synthetic-session")].into_iter().enumerate() {
        let mut payload = serde_json::json!({"text": "synthetic source"});
        if let Some(session_id) = session_id {
            payload["session_id"] = Value::String(session_id.to_owned());
        }
        let message = serde_json::json!({
            "broker_protocol_version": 1,
            "operation": "sanitize",
            "payload": payload,
            "request_id": format!("sanitize-mutation-{}", index + 1),
            "scope_id": "scope-1",
        });
        let mut connection = state("desktop");
        assert_eq!(
            validate_request(
                &canonical_json_bytes(&message).unwrap(),
                &mut connection,
                false,
            )
            .unwrap()
            .uncertain_completion,
            "possible_session_publication_or_known_session_mutation"
        );
    }
    assert_eq!(operation_replay("broker_health"), Some("startup_only"));
    assert_eq!(operation_replay("sanitize"), Some("never"));
    for operation in ["redact_pdf", "reidentify", "roundtrip", "sanitize"] {
        assert_eq!(deadline_ms(operation, true), None);
    }
    assert_eq!(
        deadline_ms("roundtrip", false),
        Some(6 * 360_000 + 3 * 60_000 + 1_000 + 2_000 + 5_000)
    );
}

#[test]
fn unicode_text_and_extension_response_boundaries_are_enforced() {
    let fixtures = fixtures();
    let field_limit = |field: &str, profile: &str| {
        fixtures["field_boundary_vectors"]
            .as_array()
            .unwrap()
            .iter()
            .find(|vector| vector["field"] == field && vector["profile"] == profile)
            .unwrap()["limit"]
            .as_u64()
            .unwrap() as usize
    };

    for (operation, remote_tner, profile, text) in [
        (
            "sanitize",
            false,
            "local",
            "ก".repeat(field_limit("text", "local")),
        ),
        (
            "detect",
            true,
            "remote_tner",
            "x".repeat(field_limit("text", "remote_tner")),
        ),
    ] {
        let mut message = serde_json::json!({
            "broker_protocol_version": 1,
            "operation": operation,
            "payload": {"text": text},
            "request_id": format!("{profile}-boundary"),
            "scope_id": "scope-1",
        });
        let mut connection = state("desktop");
        let request = validate_request(
            &canonical_json_bytes(&message).unwrap(),
            &mut connection,
            remote_tner,
        )
        .unwrap();
        if remote_tner {
            assert_eq!(request.local_detection_phases, None);
            assert_eq!(request.local_intermediate_text_chars, None);
            assert_eq!(request.remote_tner_max_calls, 501);
            assert_eq!(
                request.remote_tner_text_chars,
                Some(field_limit("text", "remote_tner") as u64)
            );
        } else {
            assert!(request.local_detection_phases.is_some());
            assert_eq!(
                request.local_intermediate_text_chars,
                Some(field_limit("local_intermediate_text_chars", "local") as u64)
            );
        }

        let oversized = format!("{}x", message["payload"]["text"].as_str().unwrap());
        message["payload"]["text"] = Value::String(oversized);
        let mut connection = state("desktop");
        assert_eq!(
            validate_request(
                &canonical_json_bytes(&message).unwrap(),
                &mut connection,
                remote_tner,
            )
            .unwrap_err()
            .code(),
            "payload_too_large"
        );
    }

    assert_eq!(
        field_limit("local_intermediate_text_chars", "local"),
        field_limit("text", "local")
    );

    let extension_limit = field_limit("extension_response_bytes", "extension");
    let mut result = serde_json::json!({
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
    });
    let base = aiguard_native_broker_protocol::success_message(
        "sanitize",
        "extension-boundary",
        result.clone(),
        "extension",
        1,
    )
    .unwrap();
    let filler = extension_limit - canonical_json_bytes(&base).unwrap().len();
    result["sanitized_text"] = Value::String(format!("x{}", "x".repeat(filler)));
    let boundary = aiguard_native_broker_protocol::success_message(
        "sanitize",
        "extension-boundary",
        result.clone(),
        "extension",
        1,
    )
    .unwrap();
    assert_eq!(
        canonical_json_bytes(&boundary).unwrap().len(),
        extension_limit
    );

    let oversized = format!("{}x", result["sanitized_text"].as_str().unwrap());
    result["sanitized_text"] = Value::String(oversized);
    assert_eq!(
        aiguard_native_broker_protocol::success_message(
            "sanitize",
            "extension-boundary",
            result,
            "extension",
            1,
        )
        .unwrap_err()
        .code(),
        "payload_too_large"
    );
}

#[test]
fn remote_tner_is_disabled_when_current_path_can_scan_non_source_text() {
    for (operation, payload) in [
        ("sanitize", serde_json::json!({"text": "synthetic source"})),
        (
            "reidentify",
            serde_json::json!({
                "session_id": "synthetic-session",
                "text": "synthetic masked text"
            }),
        ),
        (
            "roundtrip",
            serde_json::json!({
                "mode": "token",
                "provider": "ollama",
                "text": "synthetic source"
            }),
        ),
    ] {
        let message = serde_json::json!({
            "broker_protocol_version": 1,
            "operation": operation,
            "payload": payload,
            "request_id": format!("remote-disabled-{operation}"),
            "scope_id": "scope-1",
        });
        let mut connection = state("desktop");
        assert_eq!(
            validate_request(
                &canonical_json_bytes(&message).unwrap(),
                &mut connection,
                true,
            )
            .unwrap_err()
            .code(),
            "ner_unavailable"
        );
    }
}

#[test]
fn ambiguous_or_noncanonical_json_is_rejected() {
    let values: &[&[u8]] = &[
        br#"{"a":1.0}"#,
        br#"{"a":-0}"#,
        br#"{"a":9007199254740992}"#,
        br#"{"a":"\u0e01"}"#,
        br#"{"b":1,"a":2}"#,
        br#"{"a":1,"a":1}"#,
        br#" {"a":1}"#,
        b"{\"a\":1}\n",
        b"{\"value\":\"\xff\"}",
    ];
    for value in values {
        assert_eq!(
            parse_canonical_object(value).unwrap_err().code(),
            "request_invalid"
        );
    }
    let unicode = serde_json::json!({"array": [{"count": 1}], "text": "ก😀"});
    let encoded = canonical_json_bytes(&unicode).unwrap();
    assert_eq!(
        encoded,
        "{\"array\":[{\"count\":1}],\"text\":\"ก😀\"}".as_bytes()
    );
    assert_eq!(parse_canonical_object(&encoded).unwrap(), unicode);
}

#[test]
fn shared_json_depth_limit_fails_before_parser_limits() {
    let fixtures = fixtures();
    let policy = contract_file();
    for vector in fixtures["json_depth_vectors"].as_array().unwrap() {
        assert_eq!(
            vector["max_container_depth"],
            policy["serialization"]["max_container_depth"]
        );
        let result = parse_canonical_object(vector["json"].as_str().unwrap().as_bytes());
        if vector["valid"].as_bool().unwrap() {
            result.unwrap();
        } else {
            assert_eq!(
                result.unwrap_err().code(),
                vector["expect_error"].as_str().unwrap()
            );
        }
    }

    let mut value = Value::from(0);
    for _ in 0..policy["serialization"]["max_container_depth"]
        .as_u64()
        .unwrap()
    {
        value = Value::Array(vec![value]);
    }
    let value = serde_json::json!({"value": value});
    assert_eq!(
        canonical_json_bytes(&value).unwrap_err().code(),
        "request_invalid"
    );
}

#[test]
fn unknown_internal_failure_collapses_and_errors_are_value_free() {
    let sentinel = "SYNTHETIC_SECRET_SENTINEL";
    assert_eq!(safe_error_code(sentinel), "operation_failed");
    let error = ProtocolError::new("request_invalid", Some("private-request-id"));
    assert_eq!(error.to_string(), "request_invalid");
    assert!(!format!("{error:?}").contains(sentinel));
    assert!(!format!("{error:?}").contains("private-request-id"));

    let raw = canonical_json_bytes(&serde_json::json!({
        "broker_protocol_version": 1,
        "operation": "sanitize",
        "payload": {"extra": sentinel, "text": "synthetic text"},
        "request_id": "sentinel-request",
        "scope_id": "scope-1",
    }))
    .unwrap();
    let mut connection = state("desktop");
    let error = validate_request(&raw, &mut connection, false).unwrap_err();
    assert!(!error.to_string().contains(sentinel));
    assert!(!format!("{error:?}").contains(sentinel));

    let valid_raw = canonical_json_bytes(&serde_json::json!({
        "broker_protocol_version": 1,
        "operation": "sanitize",
        "payload": {"text": sentinel},
        "request_id": "private-request-id",
        "scope_id": "private-scope-id",
    }))
    .unwrap();
    let mut connection = state("desktop");
    let request = validate_request(&valid_raw, &mut connection, false).unwrap();
    let rendered = format!("{request:?}");
    assert!(!rendered.contains(sentinel));
    assert!(!rendered.contains("private-request-id"));
    assert!(!rendered.contains("private-scope-id"));

    let mut decoder = FrameDecoder::new(None).unwrap();
    let private_bytes = [250, 251, 252];
    let mut partial = ((private_bytes.len() + 1) as u32).to_be_bytes().to_vec();
    partial.extend_from_slice(&private_bytes);
    assert!(decoder.feed(&partial).unwrap().is_empty());
    let rendered = format!("{decoder:?}");
    assert!(!rendered.contains("[250, 251, 252]"));
    assert!(!rendered.contains("buffered_bytes"));
    assert!(!rendered.contains("expected_length"));
    assert!(!rendered.contains("frames_decoded"));
}
