"""Secret validation and checking utilities."""

import os
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
import yaml
from .config import SecretsConfig
from .gsm import GSMClient


class ValidationResult:
    """Container for validation results."""

    def __init__(self):
        self.missing_secrets: List[str] = []
        self.placeholder_secrets: List[Tuple[str, str]] = []
        self.missing_sa_access: List[Tuple[str, str]] = []
        self.placeholder_service_accounts: List[str] = []
        self.workflow_secrets: Set[str] = set()
        self.undefined_workflow_secrets: List[str] = []

    @property
    def has_errors(self) -> bool:
        """Check if there are any validation errors."""
        return bool(
            self.missing_secrets
            or self.placeholder_secrets
            or self.missing_sa_access
            or self.placeholder_service_accounts
            or self.undefined_workflow_secrets
        )

    def get_summary(self) -> str:
        """Get a summary of validation results."""
        lines = []

        if self.missing_secrets:
            lines.append(f"❌ {len(self.missing_secrets)} missing secrets")
        if self.placeholder_secrets:
            lines.append(f"⚠️  {len(self.placeholder_secrets)} placeholder secrets")
        if self.missing_sa_access:
            lines.append(f"❌ {len(self.missing_sa_access)} service account access issues")
        if self.placeholder_service_accounts:
            lines.append(
                f"⚠️  {len(self.placeholder_service_accounts)} placeholder service accounts"
            )
        if self.undefined_workflow_secrets:
            lines.append(f"❌ {len(self.undefined_workflow_secrets)} undefined workflow secrets")

        if not lines:
            return "✅ All checks passed"

        return "\n".join(lines)


class SecretsValidator:
    """Validator for secrets configuration and state."""

    def __init__(self, config: SecretsConfig, gsm_client: GSMClient):
        """
        Initialize validator.

        Args:
            config: Secrets configuration
            gsm_client: GSM client instance
        """
        self.config = config
        self.gsm = gsm_client

    def extract_secrets_from_workflow(self, workflow_path: Path) -> Set[str]:
        """
        Extract secret references from a GitHub Actions workflow file.

        Args:
            workflow_path: Path to workflow YAML file

        Returns:
            Set of secret names referenced in the workflow
        """
        secrets: Set[str] = set()

        try:
            with open(workflow_path, "r") as f:
                content = f.read()

            # Pattern 1: ${{ secrets.SECRET_NAME }}
            pattern1 = r"\$\{\{\s*secrets\.([A-Z_][A-Z0-9_]*)\s*\}\}"
            matches1 = re.findall(pattern1, content, re.IGNORECASE)
            secrets.update(matches1)

            # Pattern 2: ${{ env.SECRET_NAME }} - these might be from secrets
            # We'll also check environment variables that look like secrets
            pattern2 = r"\$\{\{\s*env\.([A-Z_][A-Z0-9_]*)\s*\}\}"
            matches2 = re.findall(pattern2, content, re.IGNORECASE)

            # Load YAML to check if env vars are set from secrets
            try:
                workflow_data = yaml.safe_load(content)
                if isinstance(workflow_data, dict):
                    # Check jobs.*.env for secrets
                    jobs = workflow_data.get("jobs", {})
                    for job in jobs.values():
                        if isinstance(job, dict):
                            env_vars = job.get("env", {})
                            if isinstance(env_vars, dict):
                                for key, value in env_vars.items():
                                    if isinstance(value, str) and "secrets." in value.lower():
                                        # Extract secret name from value
                                        secret_match = re.search(
                                            r"secrets\.([A-Z_][A-Z0-9_]*)",
                                            value,
                                            re.IGNORECASE,
                                        )
                                        if secret_match:
                                            secrets.add(secret_match.group(1))
            except yaml.YAMLError:
                pass  # If YAML parsing fails, we still have regex matches

            return secrets

        except FileNotFoundError:
            return set()

    def extract_secrets_from_workflows(self, workflow_dir: Path) -> Set[str]:
        """
        Extract secret references from all workflow files in a directory.

        Args:
            workflow_dir: Path to .github/workflows directory

        Returns:
            Set of all secret names referenced across workflows
        """
        secrets: Set[str] = set()

        if not workflow_dir.exists() or not workflow_dir.is_dir():
            return secrets

        for workflow_file in workflow_dir.glob("*.yml"):
            secrets.update(self.extract_secrets_from_workflow(workflow_file))

        for workflow_file in workflow_dir.glob("*.yaml"):
            secrets.update(self.extract_secrets_from_workflow(workflow_file))

        return secrets

    def check_placeholder_value(self, value: str) -> bool:
        """
        Check if a value is a placeholder.

        Args:
            value: Secret value to check

        Returns:
            True if value is a placeholder
        """
        if not value:
            return False

        placeholder_indicators = [
            "placeholder",
            "todo",
            "changeme",
            "replace",
            "your_",
            "your-",
            "xxx",
            "example",
        ]

        value_lower = value.lower()
        return any(indicator in value_lower for indicator in placeholder_indicators)

    def check_placeholder_sa(self, sa: str) -> bool:
        """
        Check if a service account email is a placeholder.

        Args:
            sa: Service account email

        Returns:
            True if SA is a placeholder
        """
        placeholder_indicators = [
            "placeholder",
            "your-project",
            "project-id",
            "example",
            "changeme",
        ]

        sa_lower = sa.lower()
        return any(indicator in sa_lower for indicator in placeholder_indicators)

    def validate_secrets(
        self,
        env: str,
        project: Optional[str] = None,
        workflow_path: Optional[Path] = None,
    ) -> ValidationResult:
        """
        Validate secrets for an environment.

        Args:
            env: Environment name
            project: Optional project name
            workflow_path: Optional path to workflow file or directory

        Returns:
            ValidationResult with findings
        """
        result = ValidationResult()

        env_config = self.config.get_environment(env)
        if not env_config:
            raise ValueError(f"Environment '{env}' not found")

        prefix = env_config.prefix or f"botmaro-{env}"

        # Extract workflow secrets if path provided
        if workflow_path:
            if workflow_path.is_file():
                result.workflow_secrets = self.extract_secrets_from_workflow(workflow_path)
            elif workflow_path.is_dir():
                result.workflow_secrets = self.extract_secrets_from_workflows(workflow_path)

        # Track all resolved secrets for source validation
        resolved_secrets = set()

        # Validate global secrets if configured
        if self.config.globals:
            globals_config = self.config.globals
            globals_prefix = globals_config.prefix

            for secret_config in globals_config.secrets:
                secret_name = f"{globals_prefix}--{secret_config.name}"
                value = self.gsm.get_secret_version(secret_name)
                if value is None:
                    result.missing_secrets.append(f"global/{secret_config.name}")
                elif self.check_placeholder_value(value):
                    result.placeholder_secrets.append(
                        (f"global/{secret_config.name}", value)
                    )
                else:
                    resolved_secrets.add(secret_config.name)

                for sa in globals_config.service_accounts:
                    if self.check_placeholder_sa(sa):
                        if sa not in result.placeholder_service_accounts:
                            result.placeholder_service_accounts.append(sa)
                    else:
                        member = (
                            f"serviceAccount:{sa}"
                            if not sa.startswith("serviceAccount:")
                            else sa
                        )
                        if not self.gsm.has_access(secret_name, member):
                            result.missing_sa_access.append(
                                (f"global/{secret_config.name}", sa)
                            )

        # Check environment-level secrets from all secret categories
        secret_categories = env_config.get_all_secret_categories()
        for category_name, secret_configs in secret_categories.items():
            for secret_config in secret_configs:
                # Skip source-referenced secrets (they don't need their own GSM entry)
                if secret_config.source:
                    if (
                        secret_config.source not in resolved_secrets
                        and secret_config.required
                    ):
                        result.missing_secrets.append(
                            f"{secret_config.name} (source: {secret_config.source})"
                        )
                    continue

                secret_name = f"{prefix}--{secret_config.name}"

                # Check if secret exists
                value = self.gsm.get_secret_version(secret_name)
                if value is None:
                    result.missing_secrets.append(secret_config.name)
                elif self.check_placeholder_value(value):
                    result.placeholder_secrets.append((secret_config.name, value))
                else:
                    resolved_secrets.add(secret_config.name)

                # Check service account access
                for sa in env_config.service_accounts:
                    if self.check_placeholder_sa(sa):
                        if sa not in result.placeholder_service_accounts:
                            result.placeholder_service_accounts.append(sa)
                    else:
                        member = (
                            f"serviceAccount:{sa}" if not sa.startswith("serviceAccount:") else sa
                        )
                        if not self.gsm.has_access(secret_name, member):
                            result.missing_sa_access.append((secret_config.name, sa))

        # Check project-specific secrets
        if project:
            project_config = env_config.projects.get(project)
            if project_config:
                project_sas = set(env_config.service_accounts)
                project_sas.update(project_config.service_accounts)

                for secret_config in project_config.secrets:
                    # Skip source-referenced secrets
                    if secret_config.source:
                        if (
                            secret_config.source not in resolved_secrets
                            and secret_config.required
                        ):
                            result.missing_secrets.append(
                                f"{project}/{secret_config.name} "
                                f"(source: {secret_config.source})"
                            )
                        continue

                    secret_name = f"{prefix}--{project}--{secret_config.name}"

                    # Check if secret exists
                    value = self.gsm.get_secret_version(secret_name)
                    if value is None:
                        result.missing_secrets.append(f"{project}/{secret_config.name}")
                    elif self.check_placeholder_value(value):
                        result.placeholder_secrets.append(
                            (f"{project}/{secret_config.name}", value)
                        )

                    # Check service account access
                    for sa in project_sas:
                        if self.check_placeholder_sa(sa):
                            if sa not in result.placeholder_service_accounts:
                                result.placeholder_service_accounts.append(sa)
                        else:
                            member = (
                                f"serviceAccount:{sa}"
                                if not sa.startswith("serviceAccount:")
                                else sa
                            )
                            if not self.gsm.has_access(secret_name, member):
                                result.missing_sa_access.append(
                                    (f"{project}/{secret_config.name}", sa)
                                )

        # Check if workflow secrets are defined in config
        if result.workflow_secrets:
            # Get all defined secrets from all secret categories
            defined_secrets = set()
            secret_categories = env_config.get_all_secret_categories()
            for category_name, secret_configs in secret_categories.items():
                defined_secrets.update({s.name for s in secret_configs})

            # Include global secrets
            if self.config.globals:
                defined_secrets.update({s.name for s in self.config.globals.secrets})

            if project:
                project_config = env_config.projects.get(project)
                if project_config:
                    defined_secrets.update({s.name for s in project_config.secrets})

            for workflow_secret in result.workflow_secrets:
                if workflow_secret not in defined_secrets:
                    result.undefined_workflow_secrets.append(workflow_secret)

        return result
