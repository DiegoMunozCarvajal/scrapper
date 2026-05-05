from pathlib import Path


SCRIPT = Path("bin/health-check.sh").read_text()


def test_check_pending_reads_pending_key():
    assert "d.get('pending'," in SCRIPT or "d['pending']" in SCRIPT


def test_health_check_is_valid_bash():
    assert "check_pending" in SCRIPT
    assert "check_scrapyd" in SCRIPT
    assert SCRIPT.startswith("#!/") or "#!/" in SCRIPT
