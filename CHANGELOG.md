# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.2] - 2026-03-14

### Fixed
- Fixed PyPI publish not triggering: `GITHUB_TOKEN` tag pushes don't trigger other workflows
- Merged publish step directly into auto-release workflow so it runs in the same pipeline
- Upgraded softprops/action-gh-release to v2

## [0.5.1] - 2026-03-14

### Fixed
- Fixed black version pin (`>=25.1.0`) to support Python 3.9 in CI
- Dropped Python 3.8 from CI matrix and requires-python (uses 3.9+ syntax)
- Added Python 3.12 and 3.13 to CI test matrix
- Upgraded actions/checkout to v5 (Node.js 22, fixes deprecation warnings)
- Pinned security dependency minimums: urllib3>=2.6.3, protobuf>=6.33.5, pyasn1>=0.6.2
- Updated repo URLs from B9ice to pawpeer org
- Applied black formatting to core.py and validator.py

## [0.5.0] - 2026-03-14

### Added
- **Secret source references (`source` field)**
  - New `source` field on `SecretConfig` allows aliasing another key's value
  - `source: SUPABASE_URL` on `NEXT_PUBLIC_SUPABASE_URL` exports `NEXT_PUBLIC_SUPABASE_URL=<SUPABASE_URL value>`
  - No separate GSM entry needed for source-referenced secrets
  - Works in environment-level and project-level secret categories
  - Source resolution checks already-loaded secrets first, then falls back to GSM lookup
- **Global namespace (`globals` config section)**
  - New top-level `globals` section for project/environment-agnostic secrets
  - Stored in a dedicated GCP project under a configurable prefix (default: `pawpeer`)
  - Automatically loaded during bootstrap for any environment
  - Available for `source` resolution from environment secrets
  - New `--scope global` filter in the `list` command
  - New `GlobalConfig` model exported from the package
- **Default value export support**
  - Secrets with `default` values are now properly included in `export` and `bootstrap` output
  - GSM values override defaults when present; defaults used when secret is absent from GSM
  - Fixed bug where `ensure_access` was called on non-existent GSM secrets when falling back to defaults

### Fixed
- Fixed `ensure_access` called on secrets not present in GSM when using default values
- Fixed MANIFEST.in referencing non-existent files (`README.secrets-manager.md`, `SETUP.secrets-manager.md`)
- Removed duplicate `SUPABASE_URL` and `TWILIO_AUTH_TOKEN` entries in `secrets.yml`
- Fixed deprecated `project.license` table format in `pyproject.toml` (now uses SPDX string)
- Removed deprecated license classifier in favor of SPDX license expression
- Fixed version mismatch between `pyproject.toml` and `__init__.py`
- Added Python 3.12 and 3.13 classifiers

## [0.4.2] - 2025-01-17

### Fixed
- **Support for multiple secret categories in secrets.yml**
  - Fixed bug where only `global_secrets` section was read from config files
  - Now correctly reads ALL sections ending with `_secrets` (e.g., `serverside_secrets`, `mobile_secrets`, `api_secrets`, etc.)
  - Updated `EnvironmentConfig.get_all_secret_categories()` to scan for all `*_secrets` fields
  - Updated `bootstrap()` command to load secrets from all categories
  - Updated `validate_secrets()` in validator to check all secret categories
  - Fixed Pydantic v2.11 deprecation warning by accessing `model_fields` from class instead of instance
  - Added comprehensive test suite for multiple secret categories
  - Maintains backward compatibility with configs that only have `global_secrets`

### Added
- New test file `tests/test_multiple_secret_categories.py` with 4 test cases covering:
  - Multiple secret categories support
  - Secret naming consistency across categories
  - Empty secret categories handling
  - Backward compatibility with `global_secrets` only configs

## [0.4.1] - 2025-01-16

### Fixed
- **Import command prefix display bug**
  - Fixed bug where import command displayed secret names without the environment prefix
  - Now correctly shows full secret name: `botmaro-staging--SENDGRID_API_KEY` instead of `staging.SENDGRID_API_KEY`
  - Updated `set_secret()` method to return full secret name in result dictionary
  - Applied consistent naming display across both `import` and `set` commands

## [0.4.0] - 2025-01-16

### Added
- **Secret Import Command (`import` command)**
  - New `secrets-manager import` command for bulk secret imports from files
  - Support for multiple file formats: .env, JSON (.json), YAML (.yml, .yaml)
  - Automatic placeholder detection and filtering (skips PLACEHOLDER, TODO, CHANGEME, etc.)
  - `--dry-run` flag for previewing changes without importing
  - `--skip-placeholders` flag to control placeholder filtering behavior
  - `--force` flag to skip confirmation prompts
  - `--grant` flag to assign service account access during import
  - `--project` flag for importing to project-scoped secrets
  - Intelligent parsing of .env files with quote handling
  - Progress tracking with success/failure counts and detailed error reporting
  - Import summary table showing preview of secrets to be imported
  - Graceful error handling for missing or malformed files

### Changed
- `--config` option now defaults to `./secrets.yml` across all commands
- Improved error messages when config file is not found
- Better file format detection for .env files (including files starting with .env)

### Security
- Automatic masking of secret values in import preview (shows first 10 characters)
- Skip empty or placeholder values by default to prevent accidental placeholder imports

## [0.3.0] - 2025-01-10

### Added
- **GitHub Actions Integration**
  - Native GitHub Actions composite action at `.github/actions/setup-secrets/`
  - Automatic secret loading from GCP Secret Manager into workflow environments
  - Workload Identity Federation support (no long-lived keys required)
  - Automatic secret masking in GitHub Actions logs for enhanced security
  - Example workflows for simple, multi-environment, matrix, and advanced patterns
  - Comprehensive documentation in `GITHUB_ACTIONS.md` with complete setup guide
- **Multi-format Secret Export (`export` command)**
  - New `secrets-manager export` command supporting multiple output formats
  - Formats: dotenv, JSON, YAML, GitHub Actions, shell scripts
  - `--github-env` flag for GitHub Actions environment file integration
  - `--github-output` flag for step outputs in GitHub Actions
  - Built-in validation before export to ensure secret integrity
  - Support for environment and project scoping
  - Enables zero-duplication secret management with GCP as single source of truth
- **Secret Formatters Module**
  - New `secrets_manager/formatters.py` with format-specific implementations
  - Comprehensive test suite for all formatters (`tests/test_formatters.py`)
  - Proper escaping and quoting for each format type
  - Support for nested structures in JSON and YAML formats

### Changed
- Updated README with enhanced CI/CD examples and export command documentation
- Improved GitHub Actions examples with best practices
- Enhanced security recommendations for Workload Identity Federation

### Fixed
- Corrected formatter implementations to match test expectations
- Applied Black formatting to `formatters.py` for code consistency

## [0.2.0] - 2025-01-08

### Added
- **Secrets validation and checking (`check` command)**
  - New `secrets-manager check` command for comprehensive validation
  - Detects missing secrets in GSM
  - Identifies placeholder values (PLACEHOLDER, TODO, changeme, etc.)
  - Identifies placeholder service accounts
  - Verifies service account access to secrets
  - Parses GitHub Actions workflow files to extract secret references
  - Validates that workflow secrets are defined in config
  - Supports both individual workflow files and directories
  - Returns error exit code for CI/CD integration
  - Color-coded output showing errors (red), warnings (yellow), and success (green)
  - Verbose mode for detailed findings
  - Use cases: pre-deployment validation, audit, troubleshooting
- **Automatic service account access grants during bootstrap**
  - Configure service accounts in `secrets.yml` at environment and project levels
  - Bootstrap command automatically grants `secretAccessor` role to configured service accounts
  - Idempotent access granting: only grants if access is missing
  - New `service_accounts` field in EnvironmentConfig and ProjectConfig
  - New GSM methods: `has_access()`, `ensure_access()`
  - Automatic inheritance: project secrets get both env-level and project-level service accounts
- Bulk IAM permission granting via `grant-access` command
  - Grant access to all secrets in an environment or project scope
  - Support for multiple service accounts via repeatable `--sa` flag
  - Interactive confirmation with preview of affected secrets
  - Python API: `grant_access_bulk()` method in SecretsManager
- Placeholder highlighting in list command
  - Placeholder values displayed in red for easy identification
  - Works with both masked and revealed values
- Scope filtering in list command
  - New `--scope` option with values: `env`, `project`, `all`
  - Filter secrets by environment-level or project-level
  - Returns 3-tuple with scope information
- Comprehensive documentation for automatic access grants and check command in README
- Auto-merge workflow: automatically merges `develop` into `main` when all tests pass
- Type checking improvements and mypy compliance

### Changed
- Bootstrap command now reads and applies service accounts from config automatically
- `--runtime-sa` and `--deployer-sa` flags now add to configured service accounts (not replace)
- Updated Python type annotations for better mypy compatibility
- Changed mypy Python version target from 3.8 to 3.9
- Clarified README documentation to emphasize this tool IS the GCP interface
- Detangled from superbot references, updated all URLs to standalone repository

### Fixed
- Code formatting with Black across all Python files
- Type checking errors in cli.py and gsm.py
- Return type annotation in parse_target function

## [0.1.0] - 2025-01-07

### Added
- Initial release of Botmaro Secrets Manager
- Multi-environment secret management with Google Secret Manager
- CLI commands: bootstrap, set, get, list, delete
- Environment-scoped and project-scoped secret organization
- Double-hyphen naming convention for hierarchical secrets
- IAM integration for service account access management
- GitHub Actions CI/CD support
- Python 3.8+ compatibility
- Rich CLI with beautiful terminal output
- Configuration via YAML files
- Secret versioning support
- Automatic secret creation and updates

### Security
- Automatic IAM permission grants for runtime service accounts
- Secret value masking in CLI output by default
- Support for reading secrets from stdin for security

[Unreleased]: https://github.com/pawpeer/botmaro-gcp-secret-manager/compare/v0.5.2...HEAD
[0.5.2]: https://github.com/pawpeer/botmaro-gcp-secret-manager/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/pawpeer/botmaro-gcp-secret-manager/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/pawpeer/botmaro-gcp-secret-manager/compare/v0.4.2...v0.5.0
[0.4.2]: https://github.com/pawpeer/botmaro-gcp-secret-manager/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/pawpeer/botmaro-gcp-secret-manager/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/pawpeer/botmaro-gcp-secret-manager/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/pawpeer/botmaro-gcp-secret-manager/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/pawpeer/botmaro-gcp-secret-manager/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/pawpeer/botmaro-gcp-secret-manager/releases/tag/v0.1.0