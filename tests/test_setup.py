def test_imports():
    import pii_redactor
    from pii_redactor import models
    from pii_redactor.ingest import file_detector, text_extractor, text_cleaner, quality_validator
    from pii_redactor.detectors import thai_id, fp_detector, tb_detector, fn_scanner
    from pii_redactor.anonymizer import fp_generator, tb_generator, anonymizer
    import pii_redactor.session_vault
    import pii_redactor.ai_client
    import pii_redactor.reverse_mapper
    import pii_redactor.output_validator
    import pii_redactor.audit
    import pii_redactor.exporter
    import pii_redactor.redactor
    import pii_redactor.reid_risk
    import pii_redactor.report

def test_sample_file_exists():
    from pathlib import Path
    assert Path("tests/sample_thai.txt").exists()
    content = Path("tests/sample_thai.txt").read_text(encoding="utf-8")
    assert "วิทยา" in content
    assert "1101200012345" in content
