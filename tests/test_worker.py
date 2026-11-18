from app.worker import Worker

def test_broadcast_progress_text():
    half = Worker.progress_text(50, 100, 2, False)
    assert "50%" in half and "50/100" in half
    assert "█████░░░░░" in half

def test_empty_broadcast():
    assert "100%" in Worker.progress_text(0, 0, 0, True)
