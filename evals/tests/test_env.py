import re

from cielo_bench.config import DEFAULT_USER_AGENT, NO_COMMIT, git_commit, load_settings, parse_env_file


def test_parse_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\nCIELO_A=1\nexport CIELO_B="two words"\nCIELO_C=3 # note\nBROKEN\n', encoding="utf-8")
    assert parse_env_file(env) == {"CIELO_A": "1", "CIELO_B": "two words", "CIELO_C": "3"}


def test_only_cielo_names_are_read_and_environment_overrides(tmp_path):
    env = tmp_path / ".env"
    env.write_text("CIELO_ANTHROPIC_MODEL=from-file\nANTHROPIC_API_KEY=should-be-ignored\n", encoding="utf-8")
    settings = load_settings(env_file=env, environ={"CIELO_ANTHROPIC_MODEL": "from-env", "OPENAI_API_KEY": "x"})
    assert settings == {"CIELO_ANTHROPIC_MODEL": "from-env"}


def test_git_commit_outside_a_repo(tmp_path):
    assert git_commit(tmp_path) == NO_COMMIT


def test_default_user_agent_is_generic():
    assert re.fullmatch(r"cielo-bench/\d+\.\d+\.\d+ \(non-commercial research benchmark\)", DEFAULT_USER_AGENT)
