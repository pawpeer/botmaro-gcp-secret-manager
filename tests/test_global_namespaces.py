"""Tests for namespaced global secret behavior."""

import pytest
from typer.testing import CliRunner

from secrets_manager.cli import app
import secrets_manager.cli as cli_module
from secrets_manager.config import (
    EnvironmentConfig,
    GlobalConfig,
    ProjectConfig,
    SecretConfig,
    SecretsConfig,
)
from secrets_manager.core import SecretListGroup, SecretsManager


class FakeGSM:
    """Minimal fake GSM client for core tests."""

    def __init__(self, values):
        self.values = dict(values)
        self.access_grants = []

    def get_secret_version(self, secret_id, version="latest"):
        return self.values.get(secret_id)

    def list_secrets(self, filter_str=None):
        secret_ids = list(self.values.keys())
        if filter_str and filter_str.startswith("name:"):
            prefix = filter_str.removeprefix("name:")
            secret_ids = [secret_id for secret_id in secret_ids if secret_id.startswith(prefix)]
        return secret_ids

    def ensure_access(self, secret_name, member):
        self.access_grants.append((secret_name, member))


def attach_fake_clients(manager, clients):
    manager._get_gsm_client = lambda project_id: clients[project_id]


def test_namespaced_globals_parse_multiple_categories():
    config = SecretsConfig(
        globals={
            "pawpeer": {
                "gcp_project": "global-project",
                "vonage_secrets": [{"name": "VONAGE_API_KEY"}],
                "netlify_deploy": [{"name": "NODE_VERSION", "required": False, "default": 20}],
            }
        }
    )

    globals_config = config.get_global_config("pawpeer")
    assert globals_config is not None
    assert globals_config.get_prefix() == "pawpeer"

    categories = globals_config.get_all_secret_categories()
    assert set(categories) == {"vonage_secrets", "netlify_deploy"}
    assert categories["vonage_secrets"][0].name == "VONAGE_API_KEY"
    assert categories["netlify_deploy"][0].default == 20


def test_legacy_single_globals_config_uses_prefix_as_default_namespace():
    config = SecretsConfig(
        globals=GlobalConfig(
            gcp_project="global-project",
            prefix="pawpeer",
            secrets=[SecretConfig(name="GLOBAL_API_KEY")],
        )
    )

    assert config.get_default_global_namespace() == "pawpeer"
    assert config.get_global_config("pawpeer") is config.globals


def test_bootstrap_exports_all_global_categories_before_env_overrides():
    config = SecretsConfig(
        globals={
            "pawpeer": {
                "gcp_project": "global-project",
                "vonage_secrets": [{"name": "SHARED_API_KEY"}],
                "netlify_deploy": [{"name": "NODE_VERSION", "required": False, "default": 20}],
            }
        },
        environments={
            "staging": EnvironmentConfig(
                name="staging",
                gcp_project="staging-project",
                prefix="pawpeer-staging",
                global_secrets=[SecretConfig(name="SHARED_API_KEY")],
            )
        },
    )
    manager = SecretsManager(config)
    attach_fake_clients(
        manager,
        {
            "global-project": FakeGSM({"pawpeer--SHARED_API_KEY": "global-value"}),
            "staging-project": FakeGSM({"pawpeer-staging--SHARED_API_KEY": "env-value"}),
        },
    )

    secrets = manager.bootstrap("staging", export_to_env=False)

    assert secrets["SHARED_API_KEY"] == "env-value"
    assert secrets["NODE_VERSION"] == "20"


def test_bootstrap_can_skip_access_grants():
    config = SecretsConfig(
        globals={
            "pawpeer": {
                "gcp_project": "global-project",
                "service_accounts": ["github-actions@example.iam.gserviceaccount.com"],
                "shared_secrets": [{"name": "SHARED_API_KEY"}],
            }
        },
        environments={
            "staging": EnvironmentConfig(
                name="staging",
                gcp_project="staging-project",
                prefix="pawpeer-staging",
                service_accounts=["runtime@example.iam.gserviceaccount.com"],
                global_secrets=[SecretConfig(name="ENV_API_KEY")],
            )
        },
    )
    global_gsm = FakeGSM({"pawpeer--SHARED_API_KEY": "global-value"})
    staging_gsm = FakeGSM({"pawpeer-staging--ENV_API_KEY": "env-value"})
    manager = SecretsManager(config)
    attach_fake_clients(
        manager,
        {
            "global-project": global_gsm,
            "staging-project": staging_gsm,
        },
    )

    secrets = manager.bootstrap("staging", export_to_env=False, grant_access=False)

    assert secrets["SHARED_API_KEY"] == "global-value"
    assert secrets["ENV_API_KEY"] == "env-value"
    assert global_gsm.access_grants == []
    assert staging_gsm.access_grants == []


def test_get_namespaced_global_secret_without_schema():
    manager = SecretsManager(SecretsConfig())
    attach_fake_clients(
        manager,
        {"global-project": FakeGSM({"pawpeer--VONAGE_API_KEY": "vonage-value"})},
    )

    value = manager.get_secret(
        env="globals",
        project="pawpeer",
        secret="VONAGE_API_KEY",
        gcp_project="global-project",
    )

    assert value == "vonage-value"


def test_get_global_secret_without_namespace_uses_single_config_namespace():
    config = SecretsConfig(
        globals={
            "pawpeer": {
                "gcp_project": "global-project",
                "vonage_secrets": [{"name": "VONAGE_API_KEY"}],
            }
        }
    )
    manager = SecretsManager(config)
    attach_fake_clients(
        manager,
        {"global-project": FakeGSM({"pawpeer--VONAGE_API_KEY": "vonage-value"})},
    )

    value = manager.get_secret(env="globals", secret="VONAGE_API_KEY")

    assert value == "vonage-value"


def test_get_global_secret_without_namespace_requires_unambiguous_config():
    config = SecretsConfig(
        globals={
            "pawpeer": {"gcp_project": "pawpeer-project"},
            "botmaro": {"gcp_project": "botmaro-project"},
        }
    )
    manager = SecretsManager(config)

    with pytest.raises(ValueError, match="Global namespace required"):
        manager.get_secret(env="globals", secret="API_KEY")


def test_get_secret_uses_config_default_when_gsm_missing():
    config = SecretsConfig(
        environments={
            "staging": EnvironmentConfig(
                name="staging",
                gcp_project="staging-project",
                prefix="pawpeer-staging",
                global_secrets=[
                    SecretConfig(
                        name="NODE_VERSION",
                        required=True,
                        default=20,
                    )
                ],
            )
        }
    )
    manager = SecretsManager(config)
    attach_fake_clients(manager, {"staging-project": FakeGSM({})})

    value = manager.get_secret(env="staging", secret="NODE_VERSION")

    assert value == "20"


def test_get_global_secret_uses_config_default_when_gsm_missing():
    config = SecretsConfig(
        globals={
            "pawpeer": {
                "gcp_project": "global-project",
                "netlify_deploy": [
                    {
                        "name": "NODE_VERSION",
                        "required": True,
                        "default": 20,
                    }
                ],
            }
        }
    )
    manager = SecretsManager(config)
    attach_fake_clients(manager, {"global-project": FakeGSM({})})

    value = manager.get_secret(env="globals", project="pawpeer", secret="NODE_VERSION")

    assert value == "20"


def test_list_secrets_excludes_globals_until_requested():
    config = SecretsConfig(
        globals={
            "pawpeer": {
                "gcp_project": "global-project",
                "vonage_secrets": [{"name": "VONAGE_API_KEY"}],
            }
        },
        environments={
            "staging": EnvironmentConfig(
                name="staging",
                gcp_project="staging-project",
                prefix="pawpeer-staging",
                global_secrets=[SecretConfig(name="SUPABASE_URL")],
            )
        },
    )
    manager = SecretsManager(config)
    attach_fake_clients(
        manager,
        {
            "global-project": FakeGSM({"pawpeer--VONAGE_API_KEY": "vonage-value"}),
            "staging-project": FakeGSM({"pawpeer-staging--SUPABASE_URL": "url"}),
        },
    )

    default_results = manager.list_secrets("staging")
    included_results = manager.list_secrets("staging", include_global=True)

    assert default_results == [("SUPABASE_URL", "url", "env")]
    assert ("VONAGE_API_KEY", "vonage-value", "global") in included_results


def test_list_secret_groups_uses_config_defaults_when_gsm_missing():
    config = SecretsConfig(
        environments={
            "staging": EnvironmentConfig(
                name="staging",
                gcp_project="staging-project",
                prefix="pawpeer-staging",
                global_secrets=[
                    SecretConfig(
                        name="NODE_VERSION",
                        required=True,
                        default=20,
                    )
                ],
            )
        }
    )
    manager = SecretsManager(config)
    attach_fake_clients(manager, {"staging-project": FakeGSM({})})

    groups = manager.list_secret_groups("staging")

    assert groups[0].secrets == [("NODE_VERSION", "20", "env")]


def test_list_secret_groups_include_env_project_and_global_categories():
    config = SecretsConfig(
        globals={
            "pawpeer": {
                "gcp_project": "global-project",
                "vonage_secrets": [{"name": "VONAGE_API_KEY"}],
            }
        },
        environments={
            "staging": EnvironmentConfig(
                name="staging",
                gcp_project="staging-project",
                prefix="pawpeer-staging",
                global_secrets=[SecretConfig(name="SUPABASE_URL")],
                projects={
                    "api": ProjectConfig(
                        project_id="api",
                        secrets=[SecretConfig(name="DATABASE_URL")],
                    )
                },
            )
        },
    )
    manager = SecretsManager(config)
    attach_fake_clients(
        manager,
        {
            "global-project": FakeGSM({"pawpeer--VONAGE_API_KEY": "vonage-value"}),
            "staging-project": FakeGSM(
                {
                    "pawpeer-staging--SUPABASE_URL": "url",
                    "pawpeer-staging--api--DATABASE_URL": "db",
                }
            ),
        },
    )

    groups = manager.list_secret_groups("staging", include_global=True)

    assert [group.title for group in groups] == [
        "Environment: staging / global_secrets",
        "Environment: staging / Project: api",
        "Globals: pawpeer / vonage_secrets",
    ]
    assert groups[0].secrets == [("SUPABASE_URL", "url", "env")]
    assert groups[2].secrets == [("VONAGE_API_KEY", "vonage-value", "global")]


def test_list_secret_groups_uses_global_defaults_when_gsm_missing():
    config = SecretsConfig(
        globals={
            "pawpeer": {
                "gcp_project": "global-project",
                "netlify_deploy": [
                    {
                        "name": "NODE_VERSION",
                        "required": True,
                        "default": 20,
                    }
                ],
            }
        }
    )
    manager = SecretsManager(config)
    attach_fake_clients(manager, {"global-project": FakeGSM({})})

    groups = manager.list_secret_groups("globals", project="pawpeer")

    assert groups == [
        SecretListGroup(
            title="Globals: pawpeer / netlify_deploy",
            scope="global",
            category="netlify_deploy",
            secrets=[("NODE_VERSION", "20", "global")],
        )
    ]


def test_list_schema_free_global_namespace_strips_prefix():
    manager = SecretsManager(SecretsConfig())
    attach_fake_clients(
        manager,
        {"global-project": FakeGSM({"pawpeer--VONAGE_API_KEY": "vonage-value"})},
    )

    groups = manager.list_secret_groups(
        "globals",
        project="pawpeer",
        global_project_id="global-project",
    )

    assert groups == [
        SecretListGroup(
            title="Globals: pawpeer",
            scope="global",
            category=None,
            secrets=[("VONAGE_API_KEY", "vonage-value", "global")],
        )
    ]


def test_cli_list_include_global_and_aliases(monkeypatch):
    calls = []

    class FakeManager:
        def list_secret_groups(
            self, env, project=None, include_global=False, global_project_id=None
        ):
            calls.append((env, project, include_global, global_project_id))
            return [
                SecretListGroup(
                    title="Environment: staging / global_secrets",
                    scope="env",
                    category="global_secrets",
                    secrets=[],
                )
            ]

    monkeypatch.setattr(cli_module, "create_manager", lambda **kwargs: FakeManager())
    runner = CliRunner()

    for args in (
        ["list", "staging", "--include", "global"],
        ["list", "staging", "--include", "globals"],
        ["list", "staging", "--global"],
        ["list", "staging", "--globals"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        assert calls[-1] == ("staging", None, True, None)


def test_cli_list_globals_namespace_target(monkeypatch):
    calls = []

    class FakeManager:
        def list_secret_groups(
            self, env, project=None, include_global=False, global_project_id=None
        ):
            calls.append((env, project, include_global, global_project_id))
            return [
                SecretListGroup(
                    title="Globals: pawpeer",
                    scope="global",
                    category=None,
                    secrets=[],
                )
            ]

    monkeypatch.setattr(cli_module, "create_manager", lambda **kwargs: FakeManager())
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["list", "globals.pawpeer", "--gcp-project", "global-project"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [("globals", "pawpeer", False, "global-project")]
