# Botmaro Secrets Manager

A standalone, environment-aware secret management tool built on Google Secret Manager (GSM). Designed for multi-environment deployments with support for both GitHub Actions workflows and local development.

## Features

- 🔐 **Multi-environment support** - Manage secrets across staging, prod, dev, and custom environments
- 🎯 **Project scoping** - Organize secrets by project within environments
- 🔄 **Version control** - Leverage GSM's built-in versioning
- 🚀 **CI/CD ready** - Bootstrap secrets in GitHub Actions or any CI/CD pipeline
- 📤 **Multiple export formats** - Export secrets in dotenv, JSON, YAML, GitHub Actions, and shell formats
- 📥 **Bulk import** - Import secrets from .env, JSON, or YAML files with automatic placeholder detection
- 🔗 **GitHub Actions integration** - Native composite action for seamless workflow integration
- 🛠️ **CRUD operations** - Full create, read, update, delete support via CLI
- ✅ **Validation & checks** - Validate secrets before deployment, detect placeholders
- 📦 **Pip installable** - Install as a standalone package
- 🎨 **Rich CLI** - Beautiful, user-friendly command-line interface
- 🔒 **IAM integration** - Automatic service account access management

## Installation

### From source (development)

```bash
# Clone the repository
git clone https://github.com/pawpeer/botmaro-gcp-secret-manager.git
cd botmaro-gcp-secret-manager

# Install in development mode
pip install -e .
```

### From PyPI (when published)

```bash
pip install botmaro-secrets-manager
```

## Quick Start

### 1. Create a configuration file

Create a `secrets.yml` file defining your environments and secrets:

```yaml
version: "1.0"

environments:
  staging:
    name: staging
    gcp_project: your-gcp-project-staging
    global_secrets:
      - name: API_KEY
        required: true
      - name: DATABASE_URL
        required: true
```

See [secrets.example.yml](secrets.example.yml) for a complete example.

### 2. Bootstrap your environment

```bash
# Load all secrets for staging environment
secrets-manager bootstrap staging

# Bootstrap with project scope
secrets-manager bootstrap staging --project myapp

# Export to a .env file
secrets-manager bootstrap staging --output .env.staging
```

### 3. Manage secrets

```bash
# Set a secret
secrets-manager set staging.API_KEY --value "sk-123456"

# Set a project-scoped secret
secrets-manager set staging.myapp.DATABASE_URL --value "postgres://..."

# Get a secret
secrets-manager get staging.API_KEY --reveal

# List all secrets
secrets-manager list staging

# Delete a secret
secrets-manager delete staging.OLD_KEY --force
```

## Usage

### Command-Line Interface

#### Bootstrap Command

Load all secrets for an environment:

```bash
secrets-manager bootstrap <environment> [OPTIONS]

Options:
  --project, -p TEXT      Project name to scope secrets
  --config, -c TEXT       Path to secrets config file
  --export/--no-export    Export secrets to environment variables [default: True]
  --runtime-sa TEXT       Runtime service account to grant access
  --deployer-sa TEXT      Deployer service account to grant access
  --output, -o TEXT       Output file for .env format
  --verbose, -v           Verbose output
```

**Examples:**

```bash
# Bootstrap staging
secrets-manager bootstrap staging

# Bootstrap with service account access grants
secrets-manager bootstrap staging \
  --runtime-sa bot@project.iam.gserviceaccount.com \
  --deployer-sa deploy@project.iam.gserviceaccount.com

# Save to .env file
secrets-manager bootstrap prod --output .env.production
```

#### Set Command

Create or update a secret:

```bash
secrets-manager set <target> [OPTIONS]

Target format:
  - env.SECRET_NAME              (environment-scoped)
  - env.project.SECRET_NAME      (project-scoped)

Options:
  --value, -v TEXT     Secret value (or read from stdin)
  --config, -c TEXT    Path to secrets config file
  --grant, -g TEXT     Service account to grant access (can be repeated)
```

**Examples:**

```bash
# Set an environment-scoped secret
secrets-manager set staging.API_KEY --value "sk-123456"

# Set a project-scoped secret
secrets-manager set staging.orchestrator.DATABASE_URL --value "postgres://..."

# Read from stdin
echo "secret-value" | secrets-manager set staging.MY_SECRET

# Grant access to service accounts
secrets-manager set staging.API_KEY --value "sk-123" \
  --grant bot@project.iam.gserviceaccount.com \
  --grant deploy@project.iam.gserviceaccount.com
```

#### Get Command

Retrieve a secret value:

```bash
secrets-manager get <target> [OPTIONS]

Options:
  --version TEXT       Secret version to retrieve [default: latest]
  --config, -c TEXT    Path to secrets config file
  --reveal             Show the full secret value
```

**Examples:**

```bash
# Get latest version (masked by default)
secrets-manager get staging.API_KEY

# Reveal full value
secrets-manager get staging.API_KEY --reveal

# Get specific version
secrets-manager get staging.API_KEY --version 2 --reveal
```

#### List Command

List all secrets in an environment:

```bash
secrets-manager list <environment> [OPTIONS]

Options:
  --project, -p TEXT   Project name to filter by
  --config, -c TEXT    Path to secrets config file
  --reveal             Show secret values
```

**Examples:**

```bash
# List all staging secrets
secrets-manager list staging

# List project-specific secrets
secrets-manager list staging --project orchestrator

# Show values (masked by default)
secrets-manager list staging --reveal
```

#### Delete Command

Delete a secret:

```bash
secrets-manager delete <target> [OPTIONS]

Options:
  --config, -c TEXT    Path to secrets config file
  --force, -f          Skip confirmation
```

**Examples:**

```bash
# Delete with confirmation prompt
secrets-manager delete staging.OLD_API_KEY

# Force delete
secrets-manager delete staging.OLD_API_KEY --force
```

#### Export Command

Export secrets in various formats for CI/CD integration:

```bash
secrets-manager export <environment> [OPTIONS]

Options:
  --project, -p TEXT       Project name to scope secrets
  --config, -c TEXT        Path to secrets config file
  --format, -f TEXT        Export format: dotenv, github-env, github-output, json, yaml, shell [default: dotenv]
  --output, -o TEXT        Output file (default: stdout)
  --mask/--no-mask         Mask secrets in logs (for GitHub Actions formats) [default: True]
  --github-env             Write directly to $GITHUB_ENV (GitHub Actions only)
  --github-output          Write directly to $GITHUB_OUTPUT (GitHub Actions only)
  --verbose, -v            Verbose output
```

**Supported Formats:**
- `dotenv` / `env` - Standard .env file format (KEY=value)
- `github-env` - GitHub Actions environment file format with multiline support
- `github-output` - GitHub Actions job outputs format
- `json` - JSON object
- `yaml` / `yml` - YAML format
- `shell` / `sh` - Shell export script

**Examples:**

```bash
# Export as .env file
secrets-manager export staging --format dotenv --output .env.staging

# Export as JSON
secrets-manager export prod --format json --output secrets.json

# Export to stdout (for piping)
secrets-manager export staging --format yaml

# Export with project scope
secrets-manager export staging --project myapp --format dotenv --output .env.myapp

# Export for GitHub Actions (in workflow)
secrets-manager export production --github-env

# Export as shell script
secrets-manager export staging --format shell --output load-secrets.sh
chmod +x load-secrets.sh
source load-secrets.sh
```

**Use Cases:**
- Export secrets for local development (.env files)
- Generate configuration files in various formats
- Load secrets into GitHub Actions workflows
- Create shell scripts for environment setup
- Generate JSON/YAML for application configuration

#### Import Command

Import secrets from files into Google Secret Manager:

```bash
secrets-manager import <environment> [OPTIONS]

Options:
  --file, -f TEXT              Path to import file (.env, .json, .yml) [required]
  --config, -c TEXT            Path to secrets config file [default: ./secrets.yml]
  --project, -p TEXT           Project name to scope imported secrets
  --dry-run                    Preview what would be imported without making changes
  --skip-placeholders/--no-skip-placeholders   Skip secrets with placeholder values [default: True]
  --force                      Skip confirmation prompt
  --grant, -g TEXT             Service account to grant access (can be repeated)
```

**Supported File Formats:**
- `.env` - Standard environment file format (KEY=value)
- `.json` - JSON object with key-value pairs
- `.yml` / `.yaml` - YAML file with key-value mappings

**Examples:**

```bash
# Import from .env file (assumes ./secrets.yml exists)
secrets-manager import staging --file .env.staging

# Import from JSON file
secrets-manager import staging --file secrets.json

# Import from YAML file
secrets-manager import prod --file env.yml

# Dry run to preview changes
secrets-manager import staging --file .env.staging --dry-run

# Import with project scope
secrets-manager import staging --file myapp.env --project myapp

# Import and grant access to service accounts
secrets-manager import staging --file .env \
  --grant bot@project.iam.gserviceaccount.com

# Use custom config file
secrets-manager import staging --file .env --config /path/to/secrets.yml

# Import including placeholders (not recommended)
secrets-manager import staging --file .env --no-skip-placeholders
```

**Features:**
- Automatically detects and skips placeholder values (PLACEHOLDER, TODO, CHANGEME, etc.)
- Supports quoted values in .env files
- Preview secrets before importing with masked values
- Detailed progress reporting with success/failure counts
- Validates file format and provides helpful error messages

**Use Cases:**
- Initial setup: Import existing secrets from .env files
- Migration: Move secrets from another system
- Bulk updates: Update multiple secrets at once
- Project onboarding: Quickly set up secrets for new team members

#### Grant Access Command

Grant access to all secrets in an environment or project:

```bash
secrets-manager grant-access <target> [OPTIONS]

Target format:
  - env                  (all environment-level secrets)
  - env.project          (all project-scoped secrets)

Options:
  --sa TEXT            Service account email to grant access (can be repeated)
  --config, -c TEXT    Path to secrets config file
  --force, -f          Skip confirmation prompt
```

**Examples:**

```bash
# Grant access to all staging secrets
secrets-manager grant-access staging \
  --sa bot@project.iam.gserviceaccount.com

# Grant to multiple service accounts
secrets-manager grant-access staging \
  --sa bot@project.iam.gserviceaccount.com \
  --sa deployer@project.iam.gserviceaccount.com

# Grant access to all project-specific secrets
secrets-manager grant-access staging.myapp \
  --sa myapp-runtime@project.iam.gserviceaccount.com

# Skip confirmation
secrets-manager grant-access staging --sa bot@project.iam.gserviceaccount.com --force
```

**Note:** This command grants the `secretmanager.secretAccessor` role, allowing the service account to read secret values.

#### Check Command

Validate secrets configuration and state:

```bash
secrets-manager check <environment> [OPTIONS]

Options:
  --project, -p TEXT      Project name to scope secrets
  --config, -c TEXT       Path to secrets config file
  --workflows, -w TEXT    Path to workflow file or .github/workflows directory
  --verbose, -v           Show detailed findings
```

This command performs comprehensive validation:
- ✅ All required secrets exist in GSM
- ✅ No placeholder values in secrets (e.g., "PLACEHOLDER_", "TODO", "changeme")
- ✅ No placeholder service accounts
- ✅ Service accounts have proper access to secrets
- ✅ Workflow secrets are defined in config (when `--workflows` provided)

**Examples:**

```bash
# Check all staging secrets
secrets-manager check staging

# Check with project scope
secrets-manager check staging --project myapp

# Validate against workflow files
secrets-manager check staging --workflows .github/workflows

# Check specific workflow file
secrets-manager check prod --workflows .github/workflows/deploy.yml --verbose

# Use in CI/CD to prevent deployment with placeholders
secrets-manager check prod && echo "Secrets validated, deploying..."
```

**Exit codes:**
- `0` - All checks passed
- `1` - Validation failed (missing secrets, placeholders, or access issues)

**Example output:**

```
Validation Summary:
⚠️  2 placeholder secrets
❌ 1 missing secrets
❌ 1 service account access issues

⚠️  Placeholder Secrets (2):
  • OPENAI_API_KEY: PLACEHOLDER_OPENAI_...
  • DATABASE_URL: TODO-replace-me

❌ Missing Secrets (1):
  • STRIPE_SECRET_KEY

❌ Missing Service Account Access (1):
  • API_KEY → runtime-bot@project.iam.gserviceaccount.com

❌ Validation failed with errors
```

**Use cases:**
- Pre-deployment validation in CI/CD pipelines
- Verify secrets before running `bootstrap`
- Audit service account access
- Ensure workflow secrets are properly configured
- Catch configuration issues early

## GitHub Actions Integration

Botmaro Secrets Manager provides native GitHub Actions integration through a composite action that automatically loads secrets from GCP Secret Manager into your workflows.

### Using the Composite Action (Recommended)

The easiest way to use secrets in GitHub Actions is with our composite action:

```yaml
name: Deploy to Production

on:
  push:
    branches: [main]

permissions:
  contents: read
  id-token: write  # Required for Workload Identity Federation

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production

    steps:
      - uses: actions/checkout@v4

      - name: Load Secrets from GCP
        uses: ./.github/actions/setup-secrets
        with:
          environment: production
          gcp-project-id: my-gcp-project
          workload-identity-provider: projects/123456789/locations/global/workloadIdentityPools/github/providers/github-provider
          service-account: github-actions@my-gcp-project.iam.gserviceaccount.com

      - name: Deploy Application
        run: |
          # All secrets are now available as environment variables
          ./deploy.sh
```

**Key Features:**
- ✅ Automatic authentication with Workload Identity Federation
- ✅ Built-in secrets validation
- ✅ Automatic secret masking in logs
- ✅ Zero secret duplication

📖 **Full Documentation**: See [GITHUB_ACTIONS.md](GITHUB_ACTIONS.md) for complete setup instructions, including Workload Identity Federation configuration.

### Manual CLI Integration

You can also use the CLI directly in your workflows:

```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install secrets-manager
        run: pip install botmaro-gcp-secret-manager

      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: projects/.../providers/github-provider
          service_account: github-actions@project.iam.gserviceaccount.com

      - name: Export secrets to GitHub environment
        run: |
          secrets-manager export production --github-env

      - name: Deploy application
        run: |
          # Secrets are now available
          echo "Deploying..."
          ./deploy.sh
```

### Setting up initial secrets

Before running in GitHub Actions, you need to populate secrets using this tool's CLI.

**Note:** This tool is your interface to Google Secret Manager. You only need `gcloud` for authentication, not for managing secrets.

```bash
# 1. Authenticate to GCP (required for API access)
gcloud auth application-default login

# 2. Use secrets-manager CLI to create and manage secrets
secrets-manager set production.API_KEY --value "sk-123456"
secrets-manager set production.DATABASE_URL --value "postgres://..."

# 3. Verify secrets were created
secrets-manager list production --reveal
```

The `secrets-manager` CLI automatically creates secrets in Google Secret Manager with proper naming conventions and IAM permissions.

## Configuration Reference

### Environment Configuration

```yaml
environments:
  <env-name>:
    name: string              # Environment name
    gcp_project: string       # GCP project ID
    prefix: string            # Optional: secret name prefix (default: botmaro-{env})

    # Optional: Service accounts that need access to all environment-level secrets
    # These will be automatically granted secretAccessor role during bootstrap
    service_accounts:
      - service-account-1@project.iam.gserviceaccount.com
      - service-account-2@project.iam.gserviceaccount.com

    global_secrets:           # Environment-level secrets
      - name: string          # Secret name
        description: string   # Optional description
        required: boolean     # Whether secret is required (default: true)
        default: string       # Optional default value

    projects:                 # Project-specific secrets
      <project-name>:
        project_id: string

        # Optional: Project-specific service accounts
        # If not specified, environment-level service accounts will be used
        service_accounts:
          - project-sa@project.iam.gserviceaccount.com

        secrets:
          - name: string
            description: string
            required: boolean
            default: string
```

### Automatic Service Account Access Grants

The tool automatically grants `secretAccessor` role to service accounts configured in `secrets.yml` during bootstrap. This ensures that your runtime and deployment service accounts always have access to the secrets they need.

**Configuration Example:**

```yaml
environments:
  staging:
    name: staging
    gcp_project: my-project-staging

    # These service accounts will automatically get access to all staging secrets
    service_accounts:
      - runtime-bot@my-project-staging.iam.gserviceaccount.com
      - deployer@my-project-staging.iam.gserviceaccount.com

    global_secrets:
      - name: API_KEY
        required: true

    projects:
      myapp:
        project_id: myapp

        # Additional service accounts for this project's secrets
        service_accounts:
          - myapp-runtime@my-project-staging.iam.gserviceaccount.com

        secrets:
          - name: DATABASE_URL
            required: true
```

**How it works:**

1. During `secrets-manager bootstrap`, the tool checks if configured service accounts have access to each secret
2. If access is missing, it automatically grants the `secretAccessor` role
3. If access already exists, it skips (idempotent operation)
4. For project-scoped secrets, both environment-level and project-level service accounts get access

**Manual override:**

You can also specify additional service accounts at runtime:

```bash
secrets-manager bootstrap staging \
  --runtime-sa additional-bot@project.iam.gserviceaccount.com \
  --deployer-sa additional-deployer@project.iam.gserviceaccount.com
```

These will be granted access **in addition to** the service accounts configured in `secrets.yml`.

## Secret Naming Convention

Secrets are stored in GSM using a **double-hyphen (`--`) convention** for hierarchical separation, while single hyphens (`-`) or underscores (`_`) are used within component names:

- **Environment-scoped**: `{prefix}--{SECRET_NAME}`
  - Example: `botmaro-staging--API_KEY`
  - Example: `my-longer-prefix--SUPABASE_URL`

- **Project-scoped**: `{prefix}--{project}--{SECRET_NAME}`
  - Example: `botmaro-staging--orchestrator--DATABASE_URL`
  - Example: `my-company-prod--my-service--API_KEY`

Where `{prefix}` defaults to `botmaro-{environment}` but can be customized.

**Why double-hyphen?**
- Provides clear, unambiguous hierarchical separation
- Easy to parse: `secret_id.split('--')`
- GSM-compliant (only allows letters, numbers, `-`, and `_`)
- Visually distinct from naming hyphens

## Local Development

### Setup

```bash
# Install dependencies
pip install -e ".[dev]"

# Set up secrets config
cp secrets.example.yml secrets.yml
# Edit secrets.yml with your configuration

# Authenticate to GCP
gcloud auth application-default login
```

### Running locally

```bash
# Bootstrap local environment
secrets-manager bootstrap dev

# Or use a custom config
secrets-manager bootstrap dev --config ./my-secrets.yml
```

## Python API

You can also use the library programmatically:

```python
from secrets_manager import SecretsManager, SecretsConfig

# Load from config file
config = SecretsConfig.from_file("secrets.yml")
manager = SecretsManager(config)

# Bootstrap environment
secrets = manager.bootstrap(env="staging", export_to_env=True)

# Set a secret
manager.set_secret(
    env="staging",
    secret="API_KEY",
    value="sk-123456",
    grant_to=["bot@project.iam.gserviceaccount.com"]
)

# Get a secret
value = manager.get_secret(env="staging", secret="API_KEY")

# List secrets
secrets = manager.list_secrets(env="staging", project="myapp")

# Grant access to all secrets in an environment
result = manager.grant_access_bulk(
    env="staging",
    service_accounts=["bot@project.iam.gserviceaccount.com", "deployer@project.iam.gserviceaccount.com"]
)
```

## IAM Permissions

The service account running the secrets manager needs:

- `secretmanager.admin` - To create/update/delete secrets
- `iam.serviceAccountUser` - To grant access to other service accounts

Grant these roles:

```bash
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:YOUR_SA@PROJECT.iam.gserviceaccount.com" \
  --role="roles/secretmanager.admin"
```

Runtime service accounts need:

- `secretmanager.secretAccessor` - To read secrets (granted automatically by the tool)

## Troubleshooting

### Authentication errors

Make sure you're authenticated to GCP:

```bash
gcloud auth application-default login
```

For CI/CD, use service account key or Workload Identity.

### Secret not found

Check that:
1. The secret exists in GSM: `gcloud secrets list --project PROJECT_ID`
2. Your config file matches the environment name
3. The GCP project ID is correct

### Permission denied

Ensure your service account has the required IAM roles listed above.

## Releasing

This project uses tag-based releases. When you're ready to publish a new version:

### 1. Update version and changelog

```bash
# Update version in pyproject.toml
vim pyproject.toml  # Change version = "0.1.0" to "0.1.1"

# Update CHANGELOG.md
vim CHANGELOG.md    # Add release notes under [Unreleased]
```

### 2. Commit changes

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "Bump version to 0.1.1"
git push origin main
```

### 3. Create and push tag

```bash
# Create an annotated tag
git tag -a v0.1.1 -m "Release v0.1.1: Description of changes"

# Push the tag (this triggers PyPI publish!)
git push origin v0.1.1
```

### What happens automatically:

1. **Version verification** - Ensures tag matches pyproject.toml version
2. **Build package** - Creates wheel and source distribution
3. **Publish to PyPI** - Uploads to PyPI (requires PYPI_API_TOKEN secret)
4. **Create GitHub Release** - Creates release page with changelog and assets

### Manual publish (if needed)

You can also manually trigger the publish workflow from GitHub Actions UI:
- Go to Actions → Publish to PyPI → Run workflow

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see LICENSE file for details.

## Support

For issues and questions:
- GitHub Issues: https://github.com/pawpeer/botmaro-gcp-secret-manager/issues
- Documentation: https://github.com/pawpeer/botmaro-gcp-secret-manager