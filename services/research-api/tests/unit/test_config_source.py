from pathlib import Path

from research_api.config import Settings, configuration_file, configuration_files


def test_repo_configuration_is_independent_of_launch_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("RESEARCH_ENV_FILE", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    expected = configuration_file()
    expected_files = configuration_files()
    monkeypatch.chdir(tmp_path)
    assert configuration_file() == expected
    assert Path(expected).is_absolute()
    assert configuration_files() == expected_files
    assert expected_files[-1] == expected


def test_explicit_file_and_environment_precedence(monkeypatch, tmp_path):
    chosen = tmp_path / "chosen.env"
    chosen.write_text("LLM_MODEL_NAME=configured-writer\n")
    monkeypatch.setenv("RESEARCH_ENV_FILE", str(chosen))
    assert configuration_file() == str(chosen)
    assert configuration_files() == (str(chosen),)
    monkeypatch.setenv("LLM_MODEL_NAME", "environment-writer")
    assert Settings(_env_file=configuration_file()).LLM_MODEL_NAME == "environment-writer"


def test_tests_and_explicit_empty_file_disable_implicit_secrets(monkeypatch):
    monkeypatch.delenv("RESEARCH_ENV_FILE", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    assert configuration_file() is None
    assert configuration_files() == ()
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("RESEARCH_ENV_FILE", "")
    assert configuration_file() is None
    assert configuration_files() == ()


def test_later_dotenv_file_overrides_models_without_erasing_service_auth(tmp_path):
    service = tmp_path / "service.env"
    root = tmp_path / "root.env"
    service.write_text("LLM_MODEL_NAME=old-model\nSUPABASE_URL=https://auth.example.test\n")
    root.write_text("LLM_MODEL_NAME=desired-model\n")
    settings = Settings(_env_file=(service, root))
    assert settings.LLM_MODEL_NAME == "desired-model"
    assert settings.SUPABASE_URL == "https://auth.example.test"


def test_empty_provider_credentials_are_treated_as_unset():
    settings = Settings(
        _env_file=None,
        OPENAI_API_KEY="",
        OPENROUTER_API_KEY="  ",
        TAVILY_API_KEY="",
        SERPER_API_KEY="",
        OPENALEX_API_KEY="",
    )

    assert settings.OPENAI_API_KEY is None
    assert settings.OPENROUTER_API_KEY is None
    assert settings.TAVILY_API_KEY is None
    assert settings.SERPER_API_KEY is None
    assert settings.OPENALEX_API_KEY is None
