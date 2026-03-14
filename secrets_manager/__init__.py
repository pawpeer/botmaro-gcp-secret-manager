"""
Botmaro Secrets Manager

A standalone secret management tool for multi-environment deployments
with Google Secret Manager.
"""

__version__ = "0.5.3"

from .core import SecretsManager
from .config import SecretConfig, EnvironmentConfig, GlobalConfig

__all__ = ["SecretsManager", "SecretConfig", "EnvironmentConfig", "GlobalConfig"]
