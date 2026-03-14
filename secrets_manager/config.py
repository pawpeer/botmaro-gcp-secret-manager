"""Configuration models and loaders for secrets management."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import yaml
import json
from pydantic import BaseModel, Field, field_validator, ConfigDict


class SecretConfig(BaseModel):
    """Configuration for a single secret."""

    name: str
    description: Optional[str] = None
    required: bool = True
    default: Optional[str] = None
    source: Optional[str] = None


class ProjectConfig(BaseModel):
    """Configuration for a project within an environment."""

    project_id: str
    secrets: List[SecretConfig] = Field(default_factory=list)
    service_accounts: List[str] = Field(default_factory=list)


class EnvironmentConfig(BaseModel):
    """Configuration for an environment (staging, prod, etc.)."""

    model_config = ConfigDict(extra="allow")

    name: str
    gcp_project: str
    prefix: Optional[str] = None
    projects: Dict[str, ProjectConfig] = Field(default_factory=dict)
    global_secrets: List[SecretConfig] = Field(default_factory=list)
    service_accounts: List[str] = Field(default_factory=list)

    @field_validator("prefix", mode="before")
    @classmethod
    def set_prefix(cls, v: Optional[str], info) -> str:
        """Auto-generate prefix if not provided."""
        if v is None and "name" in info.data:
            return f"botmaro-{info.data['name']}"
        return v or ""

    def get_all_secret_categories(self) -> Dict[str, List[SecretConfig]]:
        """
        Get all secret categories (any field ending with _secrets).

        Returns:
            Dict mapping category names to lists of SecretConfig objects.
            Example: {'global_secrets': [...], 'serverside_secrets': [...]}
        """
        secret_categories = {}

        # Iterate through all model fields
        for field_name in self.__class__.model_fields.keys():
            if field_name.endswith("_secrets"):
                value = getattr(self, field_name, [])
                if isinstance(value, list):
                    # Parse list items as SecretConfig if they're dicts
                    parsed_secrets = []
                    for item in value:
                        if isinstance(item, dict):
                            parsed_secrets.append(SecretConfig(**item))
                        elif isinstance(item, SecretConfig):
                            parsed_secrets.append(item)
                    secret_categories[field_name] = parsed_secrets

        # Also check extra fields (fields not defined in model)
        if hasattr(self, "__pydantic_extra__") and self.__pydantic_extra__:
            for field_name, value in self.__pydantic_extra__.items():
                if field_name.endswith("_secrets") and isinstance(value, list):
                    # Parse list items as SecretConfig
                    parsed_secrets = []
                    for item in value:
                        if isinstance(item, dict):
                            parsed_secrets.append(SecretConfig(**item))
                        elif isinstance(item, SecretConfig):
                            parsed_secrets.append(item)
                    secret_categories[field_name] = parsed_secrets

        return secret_categories


class GlobalConfig(BaseModel):
    """Configuration for project-agnostic global secrets."""

    gcp_project: str
    prefix: str = "pawpeer"
    secrets: List[SecretConfig] = Field(default_factory=list)
    service_accounts: List[str] = Field(default_factory=list)


class SecretsConfig(BaseModel):
    """Root configuration for all environments and secrets."""

    version: str = "1.0"
    globals: Optional[GlobalConfig] = None
    environments: Dict[str, EnvironmentConfig] = Field(default_factory=dict)

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "SecretsConfig":
        """Load configuration from YAML or JSON file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r") as f:
            if path.suffix in [".yaml", ".yml"]:
                data = yaml.safe_load(f)
            elif path.suffix == ".json":
                data = json.load(f)
            else:
                raise ValueError(f"Unsupported file type: {path.suffix}")

        return cls(**data)

    @classmethod
    def from_env(cls) -> "SecretsConfig":
        """Load configuration from environment variables."""
        config_path = os.getenv("SECRETS_CONFIG_PATH", "secrets.yml")
        return cls.from_file(config_path)

    def get_environment(self, env_name: str) -> Optional[EnvironmentConfig]:
        """Get configuration for a specific environment."""
        return self.environments.get(env_name)

    def get_project(self, env_name: str, project_name: str) -> Optional[ProjectConfig]:
        """Get configuration for a specific project in an environment."""
        env = self.get_environment(env_name)
        if env:
            return env.projects.get(project_name)
        return None
