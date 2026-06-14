"""Core secret management logic."""

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from .config import SecretConfig, SecretsConfig, EnvironmentConfig, ProjectConfig, GlobalConfig
from .gsm import GSMClient
from .validator import SecretsValidator, ValidationResult


@dataclass
class SecretListGroup:
    """Grouped secret listing for CLI presentation."""

    title: str
    scope: str
    category: Optional[str]
    secrets: List[Tuple[str, Optional[str], str]]


class SecretsManager:
    """Main secrets manager class."""

    def __init__(self, config: Optional[SecretsConfig] = None):
        """
        Initialize secrets manager.

        Args:
            config: SecretsConfig instance or None to load from env/file
        """
        self.config = config or SecretsConfig.from_env()
        self._gsm_clients: Dict[str, GSMClient] = {}

    def _get_gsm_client(self, project_id: str) -> GSMClient:
        """Get or create a GSM client for a project."""
        if project_id not in self._gsm_clients:
            self._gsm_clients[project_id] = GSMClient(project_id)
        return self._gsm_clients[project_id]

    def _is_globals(self, env: str) -> bool:
        """Check if the env refers to the globals namespace."""
        return env == "globals"

    def _get_globals_or_raise(self, namespace: Optional[str] = None) -> Tuple[str, GlobalConfig]:
        """Get globals config or raise if not configured."""
        if namespace:
            globals_config = self.config.get_global_config(namespace)
            if not globals_config:
                raise ValueError(f"Global namespace '{namespace}' not found in configuration")
            return globals_config.namespace or namespace, globals_config

        default_namespace = self.config.get_default_global_namespace()
        if not default_namespace:
            raise ValueError(
                "Global namespace required. Use 'globals.<namespace>.<SECRET_NAME>' "
                "or provide a config with exactly one globals namespace."
            )
        globals_config = self.config.get_global_config(default_namespace)
        if not globals_config:
            raise ValueError(f"Global namespace '{default_namespace}' not found in configuration")
        return default_namespace, globals_config

    def _get_global_secret_name(self, secret: str, namespace: Optional[str] = None) -> str:
        """Generate the full secret name for a global secret."""
        resolved_namespace, globals_config = self._get_globals_or_raise(namespace)
        return f"{globals_config.get_prefix() or resolved_namespace}--{secret}"

    def _get_global_project_id(
        self,
        namespace: Optional[str] = None,
        gcp_project: Optional[str] = None,
    ) -> str:
        """Resolve the GCP project for a global namespace."""
        if gcp_project:
            return gcp_project

        if namespace:
            globals_config = self.config.get_global_config(namespace)
            if globals_config:
                return globals_config.gcp_project
        else:
            default_namespace = self.config.get_default_global_namespace()
            if default_namespace:
                globals_config = self.config.get_global_config(default_namespace)
                if globals_config:
                    return globals_config.gcp_project

        env_project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
        if env_project:
            return env_project

        raise ValueError(
            "GCP project required for global secrets. Provide --gcp-project, "
            "set GOOGLE_CLOUD_PROJECT, or use a config that defines the global namespace."
        )

    def _default_value(self, value: object) -> str:
        """Convert configured defaults into exportable string values."""
        if value is None:
            return ""
        return str(value)

    def _secret_value_or_default(
        self, secret_config: SecretConfig, value: Optional[str]
    ) -> Optional[str]:
        """Return the GSM value, or the configured default when missing."""
        if value is not None:
            return value

        if secret_config.default is not None:
            return self._default_value(secret_config.default)

        return None

    def _find_secret_config(
        self, env: str, secret: str, project: Optional[str] = None
    ) -> Optional[SecretConfig]:
        """Find the config entry for a secret in the active scope."""
        if self._is_globals(env):
            namespace = project or self.config.get_default_global_namespace()
            if not namespace:
                return None

            globals_config = self.config.get_global_config(namespace)
            if not globals_config:
                return None

            for secret_configs in globals_config.get_all_secret_categories().values():
                for secret_config in secret_configs:
                    if secret_config.name == secret:
                        return secret_config
            return None

        env_config = self.config.get_environment(env)
        if not env_config:
            return None

        if project:
            project_config = env_config.projects.get(project)
            if not project_config:
                return None

            for secret_config in project_config.secrets:
                if secret_config.name == secret:
                    return secret_config
            return None

        for secret_configs in env_config.get_all_secret_categories().values():
            for secret_config in secret_configs:
                if secret_config.name == secret:
                    return secret_config

        return None

    def _get_secret_name(self, env: str, project: Optional[str], secret: str) -> str:
        """
        Generate the full secret name in GSM.

        Uses double-hyphen (--) convention for hierarchical separation:
        - Environment-scoped: {prefix}--{SECRET_NAME}
        - Project-scoped: {prefix}--{project}--{SECRET_NAME}

        This allows unambiguous parsing: secret_id.split('--')

        Args:
            env: Environment name
            project: Optional project name
            secret: Secret name

        Returns:
            Full secret ID for GSM

        Examples:
            >>> _get_secret_name("staging", None, "API_KEY")
            "botmaro-staging--API_KEY"
            >>> _get_secret_name("staging", "orchestrator", "DATABASE_URL")
            "botmaro-staging--orchestrator--DATABASE_URL"
        """
        env_config = self.config.get_environment(env)
        if not env_config:
            raise ValueError(f"Environment '{env}' not found in configuration")

        prefix = env_config.prefix or f"botmaro-{env}"

        if project:
            return f"{prefix}--{project}--{secret}"
        else:
            return f"{prefix}--{secret}"

    def bootstrap(
        self,
        env: str,
        project: Optional[str] = None,
        export_to_env: bool = True,
        runtime_sa: Optional[str] = None,
        deployer_sa: Optional[str] = None,
        grant_access: bool = True,
    ) -> Dict[str, str]:
        """
        Bootstrap an environment by loading all secrets.

        Automatically grants access to service accounts configured in secrets.yml.
        Loads global secrets first, then environment secrets (with source resolution).

        Args:
            env: Environment name (staging, prod, etc.)
            project: Optional project name to scope to
            export_to_env: Whether to export secrets to os.environ
            runtime_sa: Optional runtime service account to grant access (in addition to config)
            deployer_sa: Optional deployer service account to grant access (in addition to config)
            grant_access: Whether to grant configured service accounts access to loaded secrets

        Returns:
            Dict of secret names to values
        """
        env_config = self.config.get_environment(env)
        if not env_config:
            raise ValueError(f"Environment '{env}' not found")

        gsm = self._get_gsm_client(env_config.gcp_project)
        secrets = {}

        # Collect service accounts from config
        service_accounts_to_grant = set(env_config.service_accounts)
        if runtime_sa:
            service_accounts_to_grant.add(runtime_sa)
        if deployer_sa:
            service_accounts_to_grant.add(deployer_sa)

        # Load global secrets first (project-agnostic)
        for global_namespace, globals_config in self.config.get_global_namespaces().items():
            globals_gsm = self._get_gsm_client(globals_config.gcp_project)
            globals_prefix = globals_config.get_prefix()

            global_sas = set(globals_config.service_accounts)
            global_sas.update(service_accounts_to_grant)

            for category_name, secret_configs in globals_config.get_all_secret_categories().items():
                for secret_config in secret_configs:
                    secret_name = f"{globals_prefix}--{secret_config.name}"
                    value = globals_gsm.get_secret_version(secret_name)

                    if value is not None:
                        # Secret exists in GSM - grant access to service accounts
                        if grant_access:
                            for sa in global_sas:
                                member = (
                                    f"serviceAccount:{sa}"
                                    if not sa.startswith("serviceAccount:")
                                    else sa
                                )
                                globals_gsm.ensure_access(secret_name, member)
                    else:
                        if secret_config.required and secret_config.default is None:
                            raise ValueError(f"Required global secret '{secret_name}' not found")
                        value = self._default_value(secret_config.default)

                    secrets[secret_config.name] = value

                    if export_to_env:
                        os.environ[secret_config.name] = value

        # Load all secret categories (global_secrets, serverside_secrets, etc.)
        secret_categories = env_config.get_all_secret_categories()

        for category_name, secret_configs in secret_categories.items():
            for secret_config in secret_configs:
                # Handle source reference: copy value from another key
                if secret_config.source:
                    if secret_config.source in secrets:
                        value = secrets[secret_config.source]
                    else:
                        # Try to fetch the source secret from GSM
                        source_name = self._get_secret_name(env, None, secret_config.source)
                        value = gsm.get_secret_version(source_name)
                        if value is None:
                            raise ValueError(
                                f"Source secret '{secret_config.source}' for "
                                f"'{secret_config.name}' not found"
                            )
                else:
                    secret_name = self._get_secret_name(env, None, secret_config.name)
                    value = gsm.get_secret_version(secret_name)

                    if value is not None:
                        # Secret exists in GSM - grant access to service accounts
                        if grant_access:
                            for sa in service_accounts_to_grant:
                                member = (
                                    f"serviceAccount:{sa}"
                                    if not sa.startswith("serviceAccount:")
                                    else sa
                                )
                                gsm.ensure_access(secret_name, member)
                    else:
                        # Fall back to default value
                        if secret_config.required and secret_config.default is None:
                            raise ValueError(f"Required secret '{secret_name}' not found")
                        value = self._default_value(secret_config.default)

                secrets[secret_config.name] = value

                if export_to_env:
                    os.environ[secret_config.name] = value

        # Load project-specific secrets if project is specified
        if project:
            project_config = env_config.projects.get(project)
            if not project_config:
                raise ValueError(f"Project '{project}' not found in environment '{env}'")

            # Add project-level service accounts
            project_service_accounts = set(service_accounts_to_grant)
            if project_config.service_accounts:
                project_service_accounts.update(project_config.service_accounts)

            for secret_config in project_config.secrets:
                # Handle source reference for project secrets too
                if secret_config.source:
                    if secret_config.source in secrets:
                        value = secrets[secret_config.source]
                    else:
                        # Try env-level first, then project-level
                        source_name = self._get_secret_name(env, None, secret_config.source)
                        value = gsm.get_secret_version(source_name)
                        if value is None:
                            source_name = self._get_secret_name(env, project, secret_config.source)
                            value = gsm.get_secret_version(source_name)
                        if value is None:
                            raise ValueError(
                                f"Source secret '{secret_config.source}' for "
                                f"'{secret_config.name}' not found"
                            )
                else:
                    secret_name = self._get_secret_name(env, project, secret_config.name)
                    value = gsm.get_secret_version(secret_name)

                    if value is not None:
                        # Secret exists in GSM - grant access to service accounts
                        if grant_access:
                            for sa in project_service_accounts:
                                member = (
                                    f"serviceAccount:{sa}"
                                    if not sa.startswith("serviceAccount:")
                                    else sa
                                )
                                gsm.ensure_access(secret_name, member)
                    else:
                        # Fall back to default value
                        if secret_config.required and secret_config.default is None:
                            raise ValueError(f"Required secret '{secret_name}' not found")
                        value = self._default_value(secret_config.default)

                secrets[secret_config.name] = value

                if export_to_env:
                    os.environ[secret_config.name] = value

        return secrets

    def set_secret(
        self,
        env: str,
        secret: str,
        value: str,
        project: Optional[str] = None,
        grant_to: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """
        Set a secret value (create or update).

        Args:
            env: Environment name, or 'globals' for the global namespace
            secret: Secret name
            value: Secret value
            project: Optional project name
            grant_to: Optional list of service accounts to grant access

        Returns:
            Dict with status information including the full secret name
        """
        if self._is_globals(env):
            namespace, globals_config = self._get_globals_or_raise(project)
            gsm = self._get_gsm_client(globals_config.gcp_project)
            secret_name = self._get_global_secret_name(secret, namespace)
        else:
            env_config = self.config.get_environment(env)
            if not env_config:
                raise ValueError(f"Environment '{env}' not found")
            gsm = self._get_gsm_client(env_config.gcp_project)
            secret_name = self._get_secret_name(env, project, secret)

        result = gsm.ensure_secret(secret_name, value)

        # Add the full secret name to the result
        result["secret_name"] = secret_name

        # Grant access to specified service accounts
        if grant_to:
            for sa in grant_to:
                if not sa.startswith("serviceAccount:"):
                    sa = f"serviceAccount:{sa}"
                gsm.grant_access(secret_name, sa)

        return result

    def get_secret(
        self,
        env: str,
        secret: str,
        project: Optional[str] = None,
        version: str = "latest",
        gcp_project: Optional[str] = None,
    ) -> Optional[str]:
        """
        Get a secret value.

        Args:
            env: Environment name, or 'globals' for the global namespace
            secret: Secret name
            project: Optional project name
            version: Version to retrieve (default: latest)

        Returns:
            Secret value or None if not found
        """
        if self._is_globals(env):
            namespace = project or self.config.get_default_global_namespace()
            if not namespace:
                raise ValueError(
                    "Global namespace required. Use 'globals.<namespace>.<SECRET_NAME>' "
                    "or provide a config with exactly one globals namespace."
                )
            globals_config = self.config.get_global_config(namespace)
            project_id = self._get_global_project_id(namespace, gcp_project)
            gsm = self._get_gsm_client(project_id)
            secret_prefix = globals_config.get_prefix() if globals_config else namespace
            secret_name = f"{secret_prefix}--{secret}"
        else:
            env_config = self.config.get_environment(env)
            if not env_config:
                raise ValueError(f"Environment '{env}' not found")
            gsm = self._get_gsm_client(env_config.gcp_project)
            secret_name = self._get_secret_name(env, project, secret)

        value = gsm.get_secret_version(secret_name, version)
        secret_config = self._find_secret_config(env, secret, project)
        if secret_config:
            return self._secret_value_or_default(secret_config, value)
        return value

    def delete_secret(self, env: str, secret: str, project: Optional[str] = None) -> bool:
        """
        Delete a secret.

        Args:
            env: Environment name, or 'globals' for the global namespace
            secret: Secret name
            project: Optional project name

        Returns:
            True if deleted, False if not found
        """
        if self._is_globals(env):
            namespace, globals_config = self._get_globals_or_raise(project)
            gsm = self._get_gsm_client(globals_config.gcp_project)
            secret_name = self._get_global_secret_name(secret, namespace)
        else:
            env_config = self.config.get_environment(env)
            if not env_config:
                raise ValueError(f"Environment '{env}' not found")
            gsm = self._get_gsm_client(env_config.gcp_project)
            secret_name = self._get_secret_name(env, project, secret)

        return gsm.delete_secret(secret_name)

    def list_secrets(
        self,
        env: str,
        project: Optional[str] = None,
        scope: Optional[str] = None,
        include_global: bool = False,
        global_project_id: Optional[str] = None,
    ) -> List[Tuple[str, Optional[str], str]]:
        """
        List all secrets for an environment.

        Args:
            env: Environment name, or 'globals' for the global namespace
            project: Optional project name to filter by
            scope: Optional scope filter ('env', 'project', 'global', or 'all'/'None' for all)

        Returns:
            List of (secret_name, value, scope) tuples where scope is 'global', 'env' or 'project'
        """
        # Handle 'globals' as env directly
        if self._is_globals(env):
            namespace = project or self.config.get_default_global_namespace()
            if not namespace:
                raise ValueError(
                    "Global namespace required. Use 'globals.<namespace>' or provide "
                    "a config with exactly one globals namespace."
                )

            globals_config = self.config.get_global_config(namespace)
            project_id = self._get_global_project_id(namespace, global_project_id)
            globals_gsm = self._get_gsm_client(project_id)
            globals_prefix = globals_config.get_prefix() if globals_config else namespace

            results = []
            seen_secret_ids = set()

            if globals_config:
                for secret_configs in globals_config.get_all_secret_categories().values():
                    for secret_config in secret_configs:
                        secret_id = f"{globals_prefix}--{secret_config.name}"
                        value = globals_gsm.get_secret_version(secret_id)
                        value = self._secret_value_or_default(secret_config, value)
                        results.append((secret_config.name, value, "global"))
                        seen_secret_ids.add(secret_id)

            filter_str = f"name:{globals_prefix}--"
            secret_ids = globals_gsm.list_secrets(filter_str)
            for secret_id in secret_ids:
                if secret_id in seen_secret_ids:
                    continue
                name = self._strip_prefix(secret_id, globals_prefix)
                value = globals_gsm.get_secret_version(secret_id)
                results.append((name, value, "global"))
            return results

        env_config = self.config.get_environment(env)
        if not env_config:
            raise ValueError(f"Environment '{env}' not found")

        gsm = self._get_gsm_client(env_config.gcp_project)
        prefix = env_config.prefix or f"botmaro-{env}"

        results = []
        seen_secret_ids = set()

        if include_global or scope == "global":
            for global_namespace, globals_config in self.config.get_global_namespaces().items():
                globals_gsm = self._get_gsm_client(globals_config.gcp_project)
                globals_prefix = globals_config.get_prefix()
                for secret_configs in globals_config.get_all_secret_categories().values():
                    for secret_config in secret_configs:
                        secret_id = f"{globals_prefix}--{secret_config.name}"
                        value = globals_gsm.get_secret_version(secret_id)
                        value = self._secret_value_or_default(secret_config, value)
                        results.append((secret_config.name, value, "global"))
                        seen_secret_ids.add(secret_id)

                filter_str = f"name:{globals_prefix}--"
                secret_ids = globals_gsm.list_secrets(filter_str)

                for secret_id in secret_ids:
                    if secret_id in seen_secret_ids:
                        continue
                    name = self._strip_prefix(secret_id, globals_prefix)
                    value = globals_gsm.get_secret_version(secret_id)
                    results.append((name, value, "global"))

            # Skip env/project secrets if only globals requested by legacy API.
            if scope == "global":
                return results

        # Build filter - use double-hyphen convention
        if project:
            filter_str = f"name:{prefix}--{project}--"
        else:
            filter_str = f"name:{prefix}--"

        if project:
            if not scope or scope in ("all", "project"):
                project_config = env_config.projects.get(project)
                if project_config:
                    for secret_config in project_config.secrets:
                        secret_id = f"{prefix}--{project}--{secret_config.name}"
                        value = gsm.get_secret_version(secret_id)
                        value = self._secret_value_or_default(secret_config, value)
                        results.append((secret_config.name, value, "project"))
                        seen_secret_ids.add(secret_id)
        else:
            if not scope or scope in ("all", "env"):
                for secret_configs in env_config.get_all_secret_categories().values():
                    for secret_config in secret_configs:
                        secret_id = f"{prefix}--{secret_config.name}"
                        value = gsm.get_secret_version(secret_id)
                        value = self._secret_value_or_default(secret_config, value)
                        results.append((secret_config.name, value, "env"))
                        seen_secret_ids.add(secret_id)

        secret_ids = gsm.list_secrets(filter_str)

        for secret_id in secret_ids:
            if secret_id in seen_secret_ids:
                continue

            # Parse using double-hyphen separator
            parts = secret_id.split("--")

            # Determine scope: env-level has 2 parts (prefix--secret), project-level has 3+ parts (prefix--project--secret)
            secret_scope = "project" if len(parts) >= 3 else "env"

            # Apply scope filter if specified
            if scope and scope != "all":
                if scope == "env" and secret_scope != "env":
                    continue  # Skip project-level secrets
                elif scope == "project" and secret_scope != "project":
                    continue  # Skip env-level secrets

            if project:
                # Expected format: prefix--project--secret
                if len(parts) >= 3:
                    name = "--".join(parts[2:])  # Handle secrets with -- in name
                else:
                    name = secret_id  # Fallback
            else:
                # Expected format: prefix--secret or prefix--project--secret
                if len(parts) == 2:
                    # Environment-level: prefix--secret
                    name = parts[1]
                elif len(parts) >= 3:
                    # Project-level: prefix--project--secret
                    # For display, show as project/secret
                    project_name = parts[1]
                    secret_name = "--".join(parts[2:])
                    name = f"{project_name}/{secret_name}"
                else:
                    name = secret_id  # Fallback

            value = gsm.get_secret_version(secret_id)
            results.append((name, value, secret_scope))

        return results

    def _strip_prefix(self, secret_id: str, prefix: str) -> str:
        """Strip a GSM secret prefix from a secret id."""
        expected_prefix = f"{prefix}--"
        if secret_id.startswith(expected_prefix):
            return secret_id[len(expected_prefix) :]
        return secret_id

    def list_secret_groups(
        self,
        env: str,
        project: Optional[str] = None,
        include_global: bool = False,
        global_project_id: Optional[str] = None,
    ) -> List[SecretListGroup]:
        """List secrets grouped by environment/global category."""
        if self._is_globals(env):
            namespace = project or self.config.get_default_global_namespace()
            if not namespace:
                raise ValueError(
                    "Global namespace required. Use 'globals.<namespace>' or provide "
                    "a config with exactly one globals namespace."
                )
            return self._list_global_groups(namespace, global_project_id)

        env_config = self.config.get_environment(env)
        if not env_config:
            raise ValueError(f"Environment '{env}' not found")

        groups = self._list_environment_groups(env, env_config, project)

        if include_global:
            for namespace in self.config.get_global_namespaces().keys():
                groups.extend(self._list_global_groups(namespace, global_project_id))

        return groups

    def _list_environment_groups(
        self,
        env: str,
        env_config: EnvironmentConfig,
        project: Optional[str] = None,
    ) -> List[SecretListGroup]:
        """Build grouped listings for environment and project secrets."""
        gsm = self._get_gsm_client(env_config.gcp_project)
        prefix = env_config.prefix or f"botmaro-{env}"
        groups: List[SecretListGroup] = []

        for category_name, secret_configs in env_config.get_all_secret_categories().items():
            entries = []
            for secret_config in secret_configs:
                secret_name = self._get_secret_name(env, None, secret_config.name)
                value = gsm.get_secret_version(secret_name)
                value = self._secret_value_or_default(secret_config, value)
                entries.append((secret_config.name, value, "env"))
            groups.append(
                SecretListGroup(
                    title=f"Environment: {env} / {category_name}",
                    scope="env",
                    category=category_name,
                    secrets=entries,
                )
            )

        if project:
            project_config = env_config.projects.get(project)
            if not project_config:
                raise ValueError(f"Project '{project}' not found in environment '{env}'")
            project_entries = []
            for secret_config in project_config.secrets:
                secret_name = self._get_secret_name(env, project, secret_config.name)
                value = gsm.get_secret_version(secret_name)
                value = self._secret_value_or_default(secret_config, value)
                project_entries.append((secret_config.name, value, "project"))
            groups.append(
                SecretListGroup(
                    title=f"Environment: {env} / Project: {project}",
                    scope="project",
                    category=project,
                    secrets=project_entries,
                )
            )
            return groups

        # Include project secrets in their own groups when listing a whole environment.
        for project_name, project_config in env_config.projects.items():
            project_entries = []
            for secret_config in project_config.secrets:
                secret_name = f"{prefix}--{project_name}--{secret_config.name}"
                value = gsm.get_secret_version(secret_name)
                value = self._secret_value_or_default(secret_config, value)
                project_entries.append((secret_config.name, value, "project"))
            groups.append(
                SecretListGroup(
                    title=f"Environment: {env} / Project: {project_name}",
                    scope="project",
                    category=project_name,
                    secrets=project_entries,
                )
            )

        return groups

    def _list_global_groups(
        self,
        namespace: str,
        gcp_project: Optional[str] = None,
    ) -> List[SecretListGroup]:
        """Build grouped listings for global namespace secrets."""
        globals_config = self.config.get_global_config(namespace)
        project_id = self._get_global_project_id(namespace, gcp_project)
        globals_gsm = self._get_gsm_client(project_id)
        globals_prefix = globals_config.get_prefix() if globals_config else namespace

        if globals_config:
            groups = []
            categorized_names = set()
            for category_name, secret_configs in globals_config.get_all_secret_categories().items():
                entries = []
                for secret_config in secret_configs:
                    secret_id = f"{globals_prefix}--{secret_config.name}"
                    value = globals_gsm.get_secret_version(secret_id)
                    value = self._secret_value_or_default(secret_config, value)
                    entries.append((secret_config.name, value, "global"))
                    categorized_names.add(secret_config.name)
                groups.append(
                    SecretListGroup(
                        title=f"Globals: {namespace} / {category_name}",
                        scope="global",
                        category=category_name,
                        secrets=entries,
                    )
                )

            secret_ids = globals_gsm.list_secrets(f"name:{globals_prefix}--")
            uncategorized = []
            for secret_id in secret_ids:
                name = self._strip_prefix(secret_id, globals_prefix)
                if name in categorized_names:
                    continue
                value = globals_gsm.get_secret_version(secret_id)
                uncategorized.append((name, value, "global"))
            if uncategorized:
                groups.append(
                    SecretListGroup(
                        title=f"Globals: {namespace} / uncategorized",
                        scope="global",
                        category="uncategorized",
                        secrets=uncategorized,
                    )
                )
            return groups

        entries = []
        for secret_id in globals_gsm.list_secrets(f"name:{globals_prefix}--"):
            name = self._strip_prefix(secret_id, globals_prefix)
            value = globals_gsm.get_secret_version(secret_id)
            entries.append((name, value, "global"))

        return [
            SecretListGroup(
                title=f"Globals: {namespace}",
                scope="global",
                category=None,
                secrets=entries,
            )
        ]

    def grant_access_bulk(
        self,
        env: str,
        service_accounts: List[str],
        project: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        Grant access to all secrets in an environment or project.

        Args:
            env: Environment name
            service_accounts: List of service account emails to grant access
            project: Optional project name to scope to

        Returns:
            Dict with count of secrets updated
        """
        env_config = self.config.get_environment(env)
        if not env_config:
            raise ValueError(f"Environment '{env}' not found")

        gsm = self._get_gsm_client(env_config.gcp_project)
        prefix = env_config.prefix or f"botmaro-{env}"

        # Build filter - use double-hyphen convention
        if project:
            filter_str = f"name:{prefix}--{project}--"
        else:
            filter_str = f"name:{prefix}--"

        secret_ids = gsm.list_secrets(filter_str)

        count = 0
        for secret_id in secret_ids:
            for sa in service_accounts:
                if not sa.startswith("serviceAccount:"):
                    sa = f"serviceAccount:{sa}"
                gsm.grant_access(secret_id, sa)
            count += 1

        return {"secrets_updated": count, "service_accounts": len(service_accounts)}

    def check_secrets(
        self,
        env: str,
        project: Optional[str] = None,
        workflow_path: Optional[str] = None,
        access_check: bool = True,
    ) -> ValidationResult:
        """
        Validate secrets configuration and state.

        Checks for:
        - Missing secrets in GSM
        - Placeholder secret values
        - Placeholder service accounts
        - Missing service account access
        - Undefined workflow secrets (if workflow_path provided)

        Args:
            env: Environment name
            project: Optional project name to scope to
            workflow_path: Optional path to workflow file or .github/workflows directory
            access_check: Whether to validate configured service account IAM bindings

        Returns:
            ValidationResult with all findings

        Raises:
            ValueError: If environment not found
        """
        env_config = self.config.get_environment(env)
        if not env_config:
            raise ValueError(f"Environment '{env}' not found")

        gsm = self._get_gsm_client(env_config.gcp_project)
        validator = SecretsValidator(self.config, gsm, get_gsm_client=self._get_gsm_client)

        workflow_path_obj = Path(workflow_path) if workflow_path else None

        return validator.validate_secrets(
            env=env,
            project=project,
            workflow_path=workflow_path_obj,
            access_check=access_check,
        )
