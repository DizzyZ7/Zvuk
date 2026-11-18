from app.core.config import Settings

def test_admin_ids_from_env_style_string():
    settings = Settings(admin_ids="1001, 1002")
    assert settings.admin_ids == (1001, 1002)

def test_proxy_rotation_config():
    settings = Settings(proxies="http://proxy1:8080,socks5://proxy2:1080")
    assert settings.proxy_list == ("http://proxy1:8080", "socks5://proxy2:1080")
