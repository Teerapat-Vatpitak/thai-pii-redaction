"""Tests for Step 7: Output validation and audit logging."""

import json
import time
import uuid
from pathlib import Path

import pytest

from pii_redactor.audit import write_process_log, write_security_log
from pii_redactor.models import EntityRegistry, ReverseResult, VaultRecord
from pii_redactor.output_validator import PIILeakError, ValidationResult, validate_output
from pii_redactor.session_vault import SessionVault


def _make_vault(original: str = "safe text", pseudonym: str = "SAFE_PSEUDO") -> SessionVault:
    """Helper to create a vault with one test record."""
    vault = SessionVault()
    vault.write(
        VaultRecord(
            entity_id=str(uuid.uuid4()),
            original=original,
            pseudonym=pseudonym,
            type="TB",
            data_type="NAME",
            span=(0, len(original)),
            timestamp=time.monotonic(),
        )
    )
    return vault


def _make_reverse_result(
    text: str, flags=None, summary=None
) -> ReverseResult:
    """Helper to create a ReverseResult."""
    return ReverseResult(
        text=text,
        flags=flags or [],
        audit_summary=summary or {"total_entities": 0, "replaced_count": 0},
    )


class TestValidateOutput:
    """Tests for validate_output() function."""

    def test_validate_output_returns_validation_result(self):
        """validate_output should return a ValidationResult instance."""
        vault = _make_vault()
        rr = _make_reverse_result("This text is safe.")
        registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
        result = validate_output(rr, registry, vault)
        assert isinstance(result, ValidationResult)

    def test_validate_output_clean_text_passes(self):
        """Clean text with no PII should pass all layers."""
        vault = _make_vault()
        rr = _make_reverse_result("This text has no unexpected PII.")
        registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
        result = validate_output(rr, registry, vault)
        assert result.layer1_pii_clean
        assert result.layer2_completeness_ok
        assert result.layer3_integrity_ok
        assert result.passed

    def test_validate_output_empty_no_truncation_flag(self):
        """Short text should not trigger truncation flag."""
        vault = _make_vault()
        rr = _make_reverse_result("Short.")
        registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
        result = validate_output(rr, registry, vault)
        truncation_flags = [f for f in result.flags if "truncation" in f]
        assert len(truncation_flags) == 0

    def test_validate_output_layer2_residue_flag(self):
        """Layer 2 should flag pseudonym residue and incompleteness."""
        vault = _make_vault()
        rr = _make_reverse_result(
            "text",
            flags=["pseudonym_residue:SAFE_PS"],
            summary={"total_entities": 1, "replaced_count": 0},
        )
        registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
        result = validate_output(rr, registry, vault)
        assert not result.layer2_completeness_ok
        assert not result.passed

    def test_validate_output_halt_on_layer3(self):
        """Layer 3 failure should set halt=True."""
        vault = _make_vault()
        # Use a long text without terminal punctuation
        rr = _make_reverse_result("This is a long text without ending punctuation abcdefghij")
        registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
        result = validate_output(rr, registry, vault)
        # The last character is 'j', which is not in the punctuation set
        # So truncation flag should be present
        truncation_flags = [f for f in result.flags if "truncation" in f]
        if truncation_flags:
            assert not result.layer3_integrity_ok
            assert result.halt

    def test_validate_output_raises_on_unexpected_pii(self):
        """Unexpected PII (not in vault) should raise PIILeakError."""
        vault = SessionVault()  # Empty vault — nothing is "known"
        # Text contains a valid Thai phone (FP-detectable) not in vault
        rr = _make_reverse_result("Call 081-234-5678 please.")
        registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
        with pytest.raises(PIILeakError):
            validate_output(rr, registry, vault)

    def test_validate_output_expected_pii_ok(self):
        """PII in vault should be considered expected and not raise."""
        vault = _make_vault(original="081-234-5678", pseudonym="PHONE_1")
        # Text contains the real phone from the vault
        rr = _make_reverse_result("Call 081-234-5678 please.")
        registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
        # Should not raise
        result = validate_output(rr, registry, vault)
        assert result.layer1_pii_clean

    def test_validate_output_utf8_encoding_check(self):
        """Valid UTF-8 text should pass Layer 3."""
        vault = _make_vault()
        # Thai text: ข้อมูลส่วนตัว = personal data
        rr = _make_reverse_result("ข้อมูลส่วนตัว ข้อมูลส่วนตัว ข้อมูลส่วนตัว ข้อมูลส่วนตัว.")
        registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
        result = validate_output(rr, registry, vault)
        assert result.layer3_integrity_ok

    def test_validate_output_flags_list_populated(self):
        """Validation result flags should contain all layer flags."""
        vault = _make_vault()
        rr = _make_reverse_result(
            "text",
            flags=["pseudonym_residue:TEST"],
            summary={"total_entities": 1, "replaced_count": 0},
        )
        registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
        result = validate_output(rr, registry, vault)
        # Should have at least the residue flag and incomplete flag
        assert len(result.flags) > 0
        assert any("pseudonym_residue" in f for f in result.flags)

    def test_validate_output_thai_ending_no_truncation(self):
        """Thai has no sentence-final punctuation. Normal Thai text ending in a
        consonant must NOT be flagged as truncated (it used to → halt → the CLI
        export path raised ExportError on legitimate Thai output)."""
        vault = _make_vault()
        # >20 chars, ends in the Thai consonant 'บ' (U+0E1A)
        rr = _make_reverse_result("สวัสดีครับ ยินดีต้อนรับทุกท่านเข้าสู่ระบบ")
        registry = EntityRegistry(entities=[], fp_count=0, tb_count=0)
        result = validate_output(rr, registry, vault)
        truncation_flags = [f for f in result.flags if "truncation" in f]
        assert truncation_flags == []
        assert result.layer3_integrity_ok
        assert not result.halt


class TestAuditLogProcess:
    """Tests for write_process_log() function."""

    def test_audit_write_process_log(self, tmp_path):
        """write_process_log should create a JSONL file with correct fields."""
        session_id = str(uuid.uuid4())
        path = write_process_log(
            session_id=session_id,
            step="step1_ingest",
            entity_count=5,
            validation_result="pass",
            flags=[],
            latency_ms=123.4,
            output_dir=str(tmp_path),
        )
        assert path.exists()
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["type"] == "process"
        assert entry["step"] == "step1_ingest"
        assert entry["entity_count"] == 5
        assert entry["session_id"] == session_id
        assert entry["validation_result"] == "pass"
        assert entry["latency_ms"] == 123.4

    def test_audit_process_log_multiple_entries(self, tmp_path):
        """Multiple calls should append to the same JSONL file."""
        session_id = str(uuid.uuid4())
        path1 = write_process_log(
            session_id=session_id,
            step="step1",
            entity_count=1,
            validation_result="pass",
            flags=[],
            latency_ms=10.0,
            output_dir=str(tmp_path),
        )
        path2 = write_process_log(
            session_id=session_id,
            step="step2",
            entity_count=2,
            validation_result="warn",
            flags=["flag1"],
            latency_ms=20.0,
            output_dir=str(tmp_path),
        )
        assert path1 == path2
        lines = path1.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["step"] == "step1"
        assert json.loads(lines[1])["step"] == "step2"

    def test_audit_process_log_no_pii(self, tmp_path):
        """Process log should never contain PII values."""
        session_id = str(uuid.uuid4())
        write_process_log(
            session_id=session_id,
            step="test",
            entity_count=1,
            validation_result="pass",
            flags=["entity_id:abc123"],
            latency_ms=10.0,
            output_dir=str(tmp_path),
        )
        content = (tmp_path / f"audit_{session_id}_process.jsonl").read_text()
        # These should never appear
        assert "1101200012345" not in content  # Thai ID
        assert "081-234-5678" not in content  # Phone
        assert "real_original" not in content


class TestAuditLogSecurity:
    """Tests for write_security_log() function."""

    def test_audit_write_security_log(self, tmp_path):
        """write_security_log should create a JSONL file with correct fields."""
        session_id = str(uuid.uuid4())
        path = write_security_log(
            session_id=session_id,
            layer="layer1",
            pii_scan_result="clean",
            mapping_table_access_count=3,
            retry_count=0,
            error_type=None,
            rollback_occurred=False,
            output_dir=str(tmp_path),
        )
        assert path.exists()
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["type"] == "security"
        assert entry["layer"] == "layer1"
        assert entry["pii_scan_result"] == "clean"
        assert entry["mapping_table_access_count"] == 3
        assert entry["retry_count"] == 0
        assert entry["rollback_occurred"] is False

    def test_audit_security_log_multiple_entries(self, tmp_path):
        """Multiple calls should append to the same JSONL file."""
        session_id = str(uuid.uuid4())
        path1 = write_security_log(
            session_id=session_id,
            layer="layer1",
            pii_scan_result="clean",
            mapping_table_access_count=1,
            retry_count=0,
            error_type=None,
            rollback_occurred=False,
            output_dir=str(tmp_path),
        )
        path2 = write_security_log(
            session_id=session_id,
            layer="layer2",
            pii_scan_result="unexpected_pii",
            mapping_table_access_count=2,
            retry_count=1,
            error_type="encoding_error",
            rollback_occurred=True,
            output_dir=str(tmp_path),
        )
        assert path1 == path2
        lines = path1.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["layer"] == "layer1"
        assert json.loads(lines[1])["layer"] == "layer2"

    def test_audit_log_path_rejects_traversal(self, tmp_path):
        """A path-traversal session_id must not escape output_dir when it is
        interpolated into the log filename."""
        from pii_redactor.audit import _log_path

        p = _log_path("../../etc/passwd", "process", str(tmp_path))
        assert p.parent == Path(str(tmp_path))
        assert ".." not in p.name
        assert "/" not in p.name and "\\" not in p.name

    def test_audit_log_path_keeps_uuid_intact(self, tmp_path):
        """Sanitizing must not mangle normal uuid/hyphen session ids."""
        from pii_redactor.audit import _log_path

        sid = str(uuid.uuid4())
        p = _log_path(sid, "process", str(tmp_path))
        assert p.name == f"audit_{sid}_process.jsonl"

    def test_audit_security_log_no_pii(self, tmp_path):
        """Security log should never contain PII values."""
        session_id = str(uuid.uuid4())
        write_security_log(
            session_id=session_id,
            layer="layer1",
            pii_scan_result="clean",
            mapping_table_access_count=1,
            retry_count=0,
            error_type=None,
            rollback_occurred=False,
            output_dir=str(tmp_path),
        )
        content = (tmp_path / f"audit_{session_id}_security.jsonl").read_text()
        # These should never appear
        assert "1101200012345" not in content  # Thai ID
        assert "081-234-5678" not in content  # Phone
        assert "original_value" not in content


class TestAuditIntegration:
    """Integration tests for audit logging."""

    def test_audit_logs_have_timestamps(self, tmp_path):
        """All audit logs should have timestamps."""
        session_id = str(uuid.uuid4())
        t_before = time.time()
        write_process_log(
            session_id=session_id,
            step="test",
            entity_count=1,
            validation_result="pass",
            flags=[],
            latency_ms=1.0,
            output_dir=str(tmp_path),
        )
        t_after = time.time()
        content = (tmp_path / f"audit_{session_id}_process.jsonl").read_text()
        entry = json.loads(content.strip())
        assert "timestamp" in entry
        assert t_before <= entry["timestamp"] <= t_after

    def test_audit_logs_utf8_safe(self, tmp_path):
        """Audit logs should handle UTF-8 correctly."""
        session_id = str(uuid.uuid4())
        write_process_log(
            session_id=session_id,
            step="test_thai_ข้อมูล",
            entity_count=1,
            validation_result="pass",
            flags=["flag_ไทย"],
            latency_ms=1.0,
            output_dir=str(tmp_path),
        )
        content = (tmp_path / f"audit_{session_id}_process.jsonl").read_text(
            encoding="utf-8"
        )
        entry = json.loads(content.strip())
        assert "ข้อมูล" in entry["step"]
        assert "ไทย" in entry["flags"][0]

    def test_different_sessions_different_logs(self, tmp_path):
        """Different sessions should have separate log files."""
        session1 = str(uuid.uuid4())
        session2 = str(uuid.uuid4())
        write_process_log(
            session_id=session1,
            step="step1",
            entity_count=1,
            validation_result="pass",
            flags=[],
            latency_ms=1.0,
            output_dir=str(tmp_path),
        )
        write_process_log(
            session_id=session2,
            step="step1",
            entity_count=1,
            validation_result="pass",
            flags=[],
            latency_ms=1.0,
            output_dir=str(tmp_path),
        )
        path1 = tmp_path / f"audit_{session1}_process.jsonl"
        path2 = tmp_path / f"audit_{session2}_process.jsonl"
        assert path1.exists()
        assert path2.exists()
        assert path1 != path2
