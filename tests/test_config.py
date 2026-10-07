import pytest

from pricedin import config


@pytest.fixture(autouse=True)
def no_env_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)


def test_missing_user_agent_refuses():
    with pytest.raises(config.ConfigError):
        config.sec_user_agent()


@pytest.mark.parametrize("ua", ["Jane Doe", "Your Name your.email@example.com"])
def test_user_agent_without_real_email_refuses(monkeypatch, ua):
    monkeypatch.setenv("SEC_USER_AGENT", ua)
    with pytest.raises(config.ConfigError):
        config.sec_user_agent()


def test_user_agent_from_env_file(tmp_path):
    (tmp_path / ".env").write_text('SEC_USER_AGENT="Jane Doe jane@mail.com"\n')
    assert config.sec_user_agent() == "Jane Doe jane@mail.com"
