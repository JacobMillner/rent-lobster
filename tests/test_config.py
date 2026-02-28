from apt_scout.config import Settings

def test_settings_loads():
    s = Settings()
    assert isinstance(s.max_requests, int)