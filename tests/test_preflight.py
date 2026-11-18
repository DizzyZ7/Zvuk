from app.tools.preflight import environment_issues, tcp_reachable


def test_placeholder_secrets_are_rejected():
    problems = environment_issues({
        "BOT_TOKEN": "123456:replace_me",
        "TELEGRAM_API_HASH": "replace",
        "TELEGRAM_API_ID": "0",
        "POSTGRES_PASSWORD": "choose_a_strong_password",
    })
    assert len(problems) == 4


def test_valid_env_in_test_mode():
    problems = environment_issues({
        "BOT_TOKEN": "123456:fake_test_token",
        "TELEGRAM_API_HASH": "some_example_value",
        "TELEGRAM_API_ID": "123456",
        "POSTGRES_PASSWORD": "testpass",
        "PREMIUM_ENABLED": "false",
    })
    assert problems == []


def test_payment_flag_requires_live_verification():
    problems = environment_issues({
        "BOT_TOKEN": "123456:fake_test_token",
        "TELEGRAM_API_HASH": "value",
        "TELEGRAM_API_ID": "123456",
        "POSTGRES_PASSWORD": "pass",
        "PREMIUM_ENABLED": "true",
    })
    assert any("Premium" in problem for problem in problems)


def test_rejects_invalid_tcp_urls():
    assert not tcp_reachable("invalid", fallback_port=8081)
