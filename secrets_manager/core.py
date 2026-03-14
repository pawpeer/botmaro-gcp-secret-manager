"""Core secret management logic."""

import os
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from .config import SecretsConfig, EnvironmentConfig, ProjectConfig, GlobalConfig
from .gsm import GSMClient
from .validator import SecretsValidator, ValidationResult


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
        if self.config.globals:
            globals_config = self.config.globals
            globals_gsm = self._get_gsm_client(globals_config.gcp_project)
            globals_prefix = globals_config.prefix

            global_sas = set(globals_config.service_accounts)
            global_sas.update(service_accounts_to_grant)

            for secret_config in globals_config.secrets:
                secret_name = f"{globals_prefix}--{secret_config.name}"
                value = globals_gsm.get_secret_version(secret_name)

                if value is not None:
                    # Secret exists in GSM - grant access to service accounts
                    for sa in global_sas:
                        member = (
                            f"serviceAccount:{sa}" if not sa.startswith("serviceAccount:") else sa
                        )
                        globals_gsm.ensure_access(secret_name, member)
                else:
                    if secret_config.required and secret_config.default is None:
                        raise ValueError(f"Required global secret '{secret_name}' not found")
                    value = secret_config.default or ""

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
                        value = secret_config.default or ""

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
                        value = secret_config.default or ""

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
            env: Environment name
            secret: Secret name
            value: Secret value
            project: Optional project name
            grant_to: Optional list of service accounts to grant access

        Returns:
            Dict with status information including the full secret name
        """
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
        self, env: str, secret: str, project: Optional[str] = None, version: str = "latest"
    ) -> Optional[str]:
        """
        Get a secret value.

        Args:
            env: Environment name
            secret: Secret name
            project: Optional project name
            version: Version to retrieve (default: latest)

        Returns:
            Secret value or None if not found
        """
        env_config = self.config.get_environment(env)
        if not env_config:
            raise ValueError(f"Environment '{env}' not found")

        gsm = self._get_gsm_client(env_config.gcp_project)
        secret_name = self._get_secret_name(env, project, secret)

        return gsm.get_secret_version(secret_name, version)

    def delete_secret(self, env: str, secret: str, project: Optional[str] = None) -> bool:
        """
        Delete a secret.

        Args:
            env: Environment name
            secret: Secret name
            project: Optional project name

        Returns:
            True if deleted, False if not found
        """
        env_config = self.config.get_environment(env)
        if not env_config:
            raise ValueError(f"Environment '{env}' not found")

        gsm = self._get_gsm_client(env_config.gcp_project)
        secret_name = self._get_secret_name(env, project, secret)

        return gsm.delete_secret(secret_name)

    def list_secrets(
        self, env: str, project: Optional[str] = None, scope: Optional[str] = None
    ) -> List[Tuple[str, Optional[str], str]]:
        """
        List all secrets for an environment.

        Args:
            env: Environment name
            project: Optional project name to filter by
            scope: Optional scope filter ('env', 'project', 'global', or 'all'/'None' for all)

        Returns:
            List of (secret_name, value, scope) tuples where scope is 'global', 'env' or 'project'
        """
        env_config = self.config.get_environment(env)
        if not env_config:
            raise ValueError(f"Environment '{env}' not found")

        gsm = self._get_gsm_client(env_config.gcp_project)
        prefix = env_config.prefix or f"botmaro-{env}"

        results = []

        # Include global secrets if scope allows
        if self.config.globals and scope in (None, "all", "global"):
            globals_config = self.config.globals
            globals_gsm = self._get_gsm_client(globals_config.gcp_project)
            globals_prefix = globals_config.prefix

            filter_str = f"name:{globals_prefix}--"
            secret_ids = globals_gsm.list_secrets(filter_str)

            for secret_id in secret_ids:
                parts = secret_id.split("--")
                name = parts[1] if len(parts) == 2 else secret_id
                value = globals_gsm.get_secret_version(secret_id)
                results.append((name, value, "global"))

        # Skip env/project secrets if only globals requested
        if scope == "global":
            return results

        # Build filter - use double-hyphen convention
        if project:
            filter_str = f"name:{prefix}--{project}--"
        else:
            filter_str = f"name:{prefix}--"

        secret_ids = gsm.list_secrets(filter_str)

        for secret_id in secret_ids:
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

        Returns:
            ValidationResult with all findings

        Raises:
            ValueError: If environment not found
        """
        env_config = self.config.get_environment(env)
        if not env_config:
            raise ValueError(f"Environment '{env}' not found")

        gsm = self._get_gsm_client(env_config.gcp_project)
        validator = SecretsValidator(self.config, gsm)

        workflow_path_obj = Path(workflow_path) if workflow_path else None

        return validator.validate_secrets(env=env, project=project, workflow_path=workflow_path_obj)
