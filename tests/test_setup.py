def test_imports():
    pass


def test_sample_file_exists():
    from pathlib import Path

    assert Path("tests/sample_thai.txt").exists()
    content = Path("tests/sample_thai.txt").read_text(encoding="utf-8")
    assert "วิทยา" in content
    assert "1101200012345" in content
