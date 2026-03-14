"""Command-line interface for secrets management."""

import os
import sys
from pathlib import Path
from typing import Optional, List
import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from .core import SecretsManager
from .config import SecretsConfig
from .formatters import get_formatter, write_github_env, write_github_output

app = typer.Typer(
    name="secrets-manager",
    help="Botmaro Secrets Manager - Multi-environment secret management with Google Secret Manager",
    add_completion=False,
)
console = Console()


def parse_target(target: str) -> tuple[str, Optional[str], Optional[str]]:
    """
    Parse target string into (env, project, secret).

    Examples:
        'staging.myproject' -> ('staging', 'myproject', None)
        'staging' -> ('staging', None, None)
        'staging.myproject.MY_SECRET' -> ('staging', 'myproject', 'MY_SECRET')
        'staging.MY_SECRET' -> ('staging', None, 'MY_SECRET')
    """
    parts = target.split(".")

    if len(parts) == 1:
        # Just environment
        return parts[0], None, None
    elif len(parts) == 2:
        # Could be env.project or env.secret
        # Heuristic: if second part is uppercase, it's a secret
        if parts[1].isupper() or "_" in parts[1]:
            return parts[0], None, parts[1]
        else:
            return parts[0], parts[1], None
    elif len(parts) >= 3:
        # env.project.secret
        return parts[0], parts[1], ".".join(parts[2:])
    else:
        raise ValueError(f"Invalid target format: {target}")


@app.command()
def bootstrap(
    env: str = typer.Argument(..., help="Environment name (e.g., staging, prod)"),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project name to scope secrets"
    ),
    config: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to secrets config file"
    ),
    export: bool = typer.Option(
        True, "--export/--no-export", help="Export secrets to environment variables"
    ),
    runtime_sa: Optional[str] = typer.Option(
        None, "--runtime-sa", help="Runtime service account to grant access"
    ),
    deployer_sa: Optional[str] = typer.Option(
        None, "--deployer-sa", help="Deployer service account to grant access"
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output file for .env format"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """
    Bootstrap environment by loading all required secrets.

    This command loads all secrets defined in the configuration for the specified
    environment and optionally exports them to the current shell environment.

    Examples:
        \b
        # Bootstrap staging environment
        secrets-manager bootstrap staging

        \b
        # Bootstrap with project scope
        secrets-manager bootstrap staging --project myapp

        \b
        # Save to .env file
        secrets-manager bootstrap staging --output .env.staging
    """
    try:
        # Load config
        if config:
            os.environ["SECRETS_CONFIG_PATH"] = config

        manager = SecretsManager()

        with console.status(f"[bold green]Loading secrets for {env}..."):
            secrets = manager.bootstrap(
                env=env,
                project=project,
                export_to_env=export,
                runtime_sa=runtime_sa,
                deployer_sa=deployer_sa,
            )

        # Display results
        if verbose:
            table = Table(title=f"Loaded Secrets - {env}" + (f".{project}" if project else ""))
            table.add_column("Secret", style="cyan")
            table.add_column("Value", style="green")

            for key, value in secrets.items():
                # Mask value for security
                masked = f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "***"
                table.add_row(key, masked)

            console.print(table)
        else:
            console.print(f"[green]✓[/green] Loaded {len(secrets)} secrets for [bold]{env}[/bold]")

        # Write to output file if specified
        if output:
            output_path = Path(output)
            with open(output_path, "w") as f:
                for key, value in secrets.items():
                    f.write(f"{key}={value}\n")
            console.print(f"[green]✓[/green] Secrets written to {output_path}")

        raise typer.Exit(code=0)

    except Exception as e:
        console.print(f"[red]✗ Error:[/red] {str(e)}", style="bold red")
        raise typer.Exit(code=1)


@app.command()
def export(
    env: str = typer.Argument(..., help="Environment name (e.g., staging, prod)"),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project name to scope secrets"
    ),
    config: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to secrets config file"
    ),
    format: str = typer.Option(
        "dotenv",
        "--format",
        "-f",
        help="Export format: dotenv, github-env, github-output, json, yaml, shell",
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output file (default: stdout)"
    ),
    mask: bool = typer.Option(
        True, "--mask/--no-mask", help="Mask secrets in logs (for GitHub Actions formats)"
    ),
    github_env: bool = typer.Option(
        False, "--github-env", help="Write directly to $GITHUB_ENV (GitHub Actions only)"
    ),
    github_output: bool = typer.Option(
        False, "--github-output", help="Write directly to $GITHUB_OUTPUT (GitHub Actions only)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """
    Export secrets in various formats for CI/CD integration.

    This command exports secrets from GCP Secret Manager in different formats
    suitable for CI/CD systems, especially GitHub Actions.

    Examples:
        \\b
        # Export as .env file
        secrets-manager export staging --format dotenv --output .env.staging

        \\b
        # Export as JSON
        secrets-manager export prod --format json --output secrets.json

        \\b
        # Export for GitHub Actions (in workflow)
        secrets-manager export staging --format github-env --output $GITHUB_ENV

        \\b
        # Or use the convenience flag
        secrets-manager export staging --github-env

        \\b
        # Export as shell script
        secrets-manager export staging --format shell --output secrets.sh

        \\b
        # Export with project scope
        secrets-manager export staging --project myapp --format yaml
    """
    try:
        # Load config
        if config:
            os.environ["SECRETS_CONFIG_PATH"] = config

        manager = SecretsManager()

        # Load secrets
        with console.status(f"[bold green]Loading secrets for {env}..."):
            secrets = manager.bootstrap(
                env=env,
                project=project,
                export_to_env=False,  # Don't export to environment automatically
            )

        if verbose:
            console.print(f"[green]✓[/green] Loaded {len(secrets)} secrets")

        # Get formatter
        try:
            formatter = get_formatter(format)
        except ValueError as e:
            console.print(f"[red]✗ Error:[/red] {str(e)}", style="bold red")
            raise typer.Exit(code=1)

        # Format secrets
        formatted = formatter.format(secrets, mask=mask)

        # Handle GitHub Actions special cases
        if github_env:
            try:
                write_github_env(secrets, mask=mask)
                console.print("[green]✓[/green] Secrets written to $GITHUB_ENV")
                raise typer.Exit(code=0)
            except RuntimeError as e:
                console.print(f"[red]✗ Error:[/red] {str(e)}", style="bold red")
                raise typer.Exit(code=1)

        if github_output:
            try:
                write_github_output(secrets, mask=mask)
                console.print("[green]✓[/green] Secrets written to $GITHUB_OUTPUT")
                raise typer.Exit(code=0)
            except RuntimeError as e:
                console.print(f"[red]✗ Error:[/red] {str(e)}", style="bold red")
                raise typer.Exit(code=1)

        # Write to file or stdout
        if output:
            output_path = Path(output)
            with open(output_path, "w") as f:
                f.write(formatted)
                if not formatted.endswith("\n"):
                    f.write("\n")

            console.print(f"[green]✓[/green] Secrets exported to {output_path} ({format} format)")
        else:
            # Output to stdout
            console.print(formatted)

        raise typer.Exit(code=0)

    except Exception as e:
        console.print(f"[red]✗ Error:[/red] {str(e)}", style="bold red")
        raise typer.Exit(code=1)


@app.command()
def set(
    target: str = typer.Argument(..., help="Target in format 'env[.project].SECRET_NAME'"),
    value: Optional[str] = typer.Option(None, "--value", "-v", help="Secret value (or use stdin)"),
    config: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to secrets config file"
    ),
    grant: Optional[List[str]] = typer.Option(
        None, "--grant", "-g", help="Service accounts to grant access"
    ),
):
    """
    Set a secret value (create or update).

    Examples:
        \b
        # Set an environment-scoped secret
        secrets-manager set staging.API_KEY --value "sk-123456"

        \b
        # Set a project-scoped secret
        secrets-manager set staging.myapp.DATABASE_URL --value "postgres://..."

        \b
        # Read value from stdin
        echo "secret-value" | secrets-manager set staging.MY_SECRET

        \b
        # Grant access to service account
        secrets-manager set staging.API_KEY --value "sk-123" --grant bot@project.iam.gserviceaccount.com
    """
    try:
        # Load config
        if config:
            os.environ["SECRETS_CONFIG_PATH"] = config

        manager = SecretsManager()

        # Parse target
        env, project, secret = parse_target(target)

        if not secret:
            console.print("[red]✗ Error:[/red] Secret name required in target", style="bold red")
            raise typer.Exit(code=1)

        # Get value from stdin if not provided
        if value is None:
            if not sys.stdin.isatty():
                value = sys.stdin.read().strip()
            else:
                value = typer.prompt("Enter secret value", hide_input=True)

        # Set the secret
        with console.status(f"[bold green]Setting secret..."):
            result = manager.set_secret(
                env=env,
                secret=secret,
                value=value,
                project=project,
                grant_to=grant,
            )

        # Use the full secret name from the result (includes prefix)
        full_secret_name = result.get("secret_name", secret)
        console.print(f"[green]✓[/green] Secret [bold]{full_secret_name}[/bold] {result['status']}")
        console.print(f"  Version: {result['version']}")

        raise typer.Exit(code=0)

    except Exception as e:
        console.print(f"[red]✗ Error:[/red] {str(e)}", style="bold red")
        raise typer.Exit(code=1)


@app.command()
def get(
    target: str = typer.Argument(..., help="Target in format 'env[.project].SECRET_NAME'"),
    version: str = typer.Option("latest", "--version", help="Secret version to retrieve"),
    config: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to secrets config file"
    ),
    reveal: bool = typer.Option(False, "--reveal", help="Show the full secret value"),
):
    """
    Get a secret value.

    Examples:
        \b
        # Get latest version of a secret
        secrets-manager get staging.API_KEY --reveal

        \b
        # Get specific version
        secrets-manager get staging.API_KEY --version 2
    """
    try:
        # Load config
        if config:
            os.environ["SECRETS_CONFIG_PATH"] = config

        manager = SecretsManager()

        # Parse target
        env, project, secret = parse_target(target)

        if not secret:
            console.print("[red]✗ Error:[/red] Secret name required in target", style="bold red")
            raise typer.Exit(code=1)

        # Get the secret
        value = manager.get_secret(env=env, secret=secret, project=project, version=version)

        if value is None:
            console.print(f"[yellow]![/yellow] Secret not found", style="bold yellow")
            raise typer.Exit(code=1)

        if reveal:
            console.print(value)
        else:
            masked = f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "***"
            console.print(f"Value: {masked} (use --reveal to show full value)")

        raise typer.Exit(code=0)

    except Exception as e:
        console.print(f"[red]✗ Error:[/red] {str(e)}", style="bold red")
        raise typer.Exit(code=1)


@app.command()
def delete(
    target: str = typer.Argument(..., help="Target in format 'env[.project].SECRET_NAME'"),
    config: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to secrets config file"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """
    Delete a secret.

    Examples:
        \b
        # Delete a secret
        secrets-manager delete staging.OLD_API_KEY

        \b
        # Force delete without confirmation
        secrets-manager delete staging.OLD_API_KEY --force
    """
    try:
        # Load config
        if config:
            os.environ["SECRETS_CONFIG_PATH"] = config

        manager = SecretsManager()

        # Parse target
        env, project, secret = parse_target(target)

        if not secret:
            console.print("[red]✗ Error:[/red] Secret name required in target", style="bold red")
            raise typer.Exit(code=1)

        target_str = f"{env}.{project}.{secret}" if project else f"{env}.{secret}"

        # Confirm deletion
        if not force:
            confirm = typer.confirm(f"Delete secret '{target_str}'?")
            if not confirm:
                console.print("Cancelled")
                raise typer.Exit(code=0)

        # Delete the secret
        deleted = manager.delete_secret(env=env, secret=secret, project=project)

        if deleted:
            console.print(f"[green]✓[/green] Secret [bold]{target_str}[/bold] deleted")
        else:
            console.print(f"[yellow]![/yellow] Secret not found", style="bold yellow")

        raise typer.Exit(code=0)

    except Exception as e:
        console.print(f"[red]✗ Error:[/red] {str(e)}", style="bold red")
        raise typer.Exit(code=1)


@app.command()
def list(
    env: str = typer.Argument(..., help="Environment name"),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project name to filter by"
    ),
    config: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to secrets config file"
    ),
    reveal: bool = typer.Option(False, "--reveal", help="Show secret values"),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        help="Filter by scope: 'env' (environment-level only), 'project' (project-level only), 'global' (global namespace only), or 'all' (default)",
    ),
):
    """
    List all secrets for an environment.

    Examples:
        \b
        # List all secrets for staging
        secrets-manager list staging

        \b
        # List secrets for a specific project
        secrets-manager list staging --project myapp

        \b
        # List only environment-level secrets
        secrets-manager list staging --scope env

        \b
        # List only project-scoped secrets
        secrets-manager list staging --scope project
    """
    try:
        # Load config
        if config:
            os.environ["SECRETS_CONFIG_PATH"] = config

        manager = SecretsManager()

        # Validate scope option
        if scope and scope not in ["env", "project", "global", "all"]:
            console.print(
                "[red]✗ Error:[/red] --scope must be one of: env, project, global, all",
                style="bold red",
            )
            raise typer.Exit(code=1)

        # List secrets
        with console.status(f"[bold green]Loading secrets..."):
            secrets = manager.list_secrets(env=env, project=project, scope=scope)

        # Display results
        scope_label = ""
        if scope == "env":
            scope_label = " (environment-level only)"
        elif scope == "project":
            scope_label = " (project-level only)"
        elif scope == "global":
            scope_label = " (global namespace only)"

        table = Table(title=f"Secrets - {env}" + (f".{project}" if project else "") + scope_label)
        table.add_column("Secret Name", style="cyan")
        table.add_column("Scope", style="yellow")
        table.add_column("Value", style="green")

        for name, value, secret_scope in secrets:
            if value and reveal:
                # Check if value is a placeholder
                if value.startswith("PLACEHOLDER") or "placeholder" in value.lower():
                    table.add_row(name, secret_scope, f"[red]{value}[/red]")
                else:
                    table.add_row(name, secret_scope, value)
            elif value:
                # Check if value is a placeholder
                if value.startswith("PLACEHOLDER") or "placeholder" in value.lower():
                    table.add_row(name, secret_scope, "[red]PLACEHOLDER[/red]")
                else:
                    masked = f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "***"
                    table.add_row(name, secret_scope, masked)
            else:
                table.add_row(name, secret_scope, "[red]<not found>[/red]")

        console.print(table)
        console.print(f"\nTotal: {len(secrets)} secrets")

        raise typer.Exit(code=0)

    except Exception as e:
        console.print(f"[red]✗ Error:[/red] {str(e)}", style="bold red")
        raise typer.Exit(code=1)


@app.command()
def grant_access(
    target: str = typer.Argument(
        ..., help="Target in format 'env' or 'env.project' to grant access to all secrets"
    ),
    service_account: List[str] = typer.Option(
        ..., "--sa", help="Service account email(s) to grant access (can be repeated)"
    ),
    config: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to secrets config file"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
):
    """
    Grant access to all secrets in an environment or project.

    This grants secretAccessor role to the specified service account(s) for
    all secrets in the given scope.

    Examples:
        \b
        # Grant access to all staging secrets
        secrets-manager grant-access staging --sa bot@project.iam.gserviceaccount.com

        \b
        # Grant access to multiple service accounts
        secrets-manager grant-access staging \\
          --sa bot@project.iam.gserviceaccount.com \\
          --sa deployer@project.iam.gserviceaccount.com

        \b
        # Grant access to project-specific secrets
        secrets-manager grant-access staging.myapp --sa runtime@project.iam.gserviceaccount.com
    """
    try:
        # Load config
        if config:
            os.environ["SECRETS_CONFIG_PATH"] = config

        manager = SecretsManager()

        # Parse target
        env, project, secret = parse_target(target)

        if secret:
            console.print(
                "[red]✗ Error:[/red] grant-access works on environment or project level, not individual secrets",
                style="bold red",
            )
            console.print(
                "Use 'secrets-manager set <target> --value ... --grant ...' for individual secrets"
            )
            raise typer.Exit(code=1)

        # Show what will be affected
        target_str = f"{env}.{project}" if project else env
        scope = f"project '{project}' in environment '{env}'" if project else f"environment '{env}'"

        console.print(f"[bold]Will grant access to all secrets in {scope}[/bold]")
        console.print(f"Service accounts:")
        for sa in service_account:
            console.print(f"  - {sa}")

        # List affected secrets
        with console.status(f"[bold green]Finding secrets..."):
            secrets = manager.list_secrets(env=env, project=project)

        console.print(f"\nAffected secrets ({len(secrets)}):")
        for name, _, _ in secrets[:10]:  # Show first 10 (unpack 3-tuple)
            console.print(f"  - {name}")
        if len(secrets) > 10:
            console.print(f"  ... and {len(secrets) - 10} more")

        # Confirm
        if not force:
            console.print()
            confirm = typer.confirm(
                f"Grant access to {len(service_account)} service account(s) for {len(secrets)} secret(s)?"
            )
            if not confirm:
                console.print("Cancelled")
                raise typer.Exit(code=0)

        # Grant access
        with console.status(f"[bold green]Granting access..."):
            result = manager.grant_access_bulk(
                env=env, service_accounts=service_account, project=project
            )

        console.print(
            f"[green]✓[/green] Granted access to {result['secrets_updated']} secrets "
            f"for {result['service_accounts']} service account(s)"
        )

        raise typer.Exit(code=0)

    except Exception as e:
        console.print(f"[red]✗ Error:[/red] {str(e)}", style="bold red")
        raise typer.Exit(code=1)


@app.command()
def check(
    env: str = typer.Argument(..., help="Environment name (e.g., staging, prod)"),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project name to scope secrets"
    ),
    config: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to secrets config file"
    ),
    workflows: Optional[str] = typer.Option(
        None, "--workflows", "-w", help="Path to workflow file or .github/workflows directory"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed findings"),
):
    """
    Check and validate secrets configuration and state.

    This command validates:
    - All required secrets exist in GSM
    - No placeholder values in secrets
    - No placeholder service accounts
    - Service accounts have proper access
    - Workflow secrets are defined (if --workflows provided)

    Examples:
        \\b
        # Check all staging secrets
        secrets-manager check staging

        \\b
        # Check with project scope
        secrets-manager check staging --project myapp

        \\b
        # Check against workflow files
        secrets-manager check staging --workflows .github/workflows

        \\b
        # Check a specific workflow file
        secrets-manager check prod --workflows .github/workflows/deploy.yml
    """
    try:
        # Load config
        if config:
            os.environ["SECRETS_CONFIG_PATH"] = config

        manager = SecretsManager()

        with console.status(f"[bold green]Checking secrets for {env}..."):
            result = manager.check_secrets(
                env=env,
                project=project,
                workflow_path=workflows,
            )

        # Display summary
        console.print(f"\n[bold]Validation Summary:[/bold]")
        console.print(result.get_summary())

        # Display detailed findings if verbose or if there are errors
        if verbose or result.has_errors:
            console.print()

            if result.missing_secrets:
                console.print(
                    f"\n[bold red]❌ Missing Secrets ({len(result.missing_secrets)}):[/bold red]"
                )
                for secret in result.missing_secrets:
                    console.print(f"  • {secret}")

            if result.placeholder_secrets:
                console.print(
                    f"\n[bold yellow]⚠️  Placeholder Secrets ({len(result.placeholder_secrets)}):[/bold yellow]"
                )
                for secret, value in result.placeholder_secrets:
                    masked = f"{value[:20]}..." if len(value) > 20 else value
                    console.print(f"  • {secret}: {masked}")

            if result.placeholder_service_accounts:
                console.print(
                    f"\n[bold yellow]⚠️  Placeholder Service Accounts ({len(result.placeholder_service_accounts)}):[/bold yellow]"
                )
                for sa in result.placeholder_service_accounts:
                    console.print(f"  • {sa}")

            if result.missing_sa_access:
                console.print(
                    f"\n[bold red]❌ Missing Service Account Access ({len(result.missing_sa_access)}):[/bold red]"
                )
                for secret, sa in result.missing_sa_access:
                    console.print(f"  • {secret} → {sa}")

            if result.undefined_workflow_secrets:
                console.print(
                    f"\n[bold red]❌ Undefined Workflow Secrets ({len(result.undefined_workflow_secrets)}):[/bold red]"
                )
                console.print(
                    "  These secrets are referenced in workflows but not defined in secrets.yml:"
                )
                for secret in result.undefined_workflow_secrets:
                    console.print(f"  • {secret}")

            if result.workflow_secrets and verbose:
                console.print(
                    f"\n[bold]📋 Workflow Secrets Found ({len(result.workflow_secrets)}):[/bold]"
                )
                for secret in sorted(result.workflow_secrets):
                    defined = "✓" if secret not in result.undefined_workflow_secrets else "✗"
                    console.print(f"  {defined} {secret}")

        # Exit with error code if there are issues
        if result.has_errors:
            console.print(f"\n[bold red]❌ Validation failed with errors[/bold red]")
            raise typer.Exit(code=1)
        else:
            console.print(f"\n[bold green]✅ All checks passed![/bold green]")
            raise typer.Exit(code=0)

    except Exception as e:
        console.print(f"[red]✗ Error:[/red] {str(e)}", style="bold red")
        raise typer.Exit(code=1)


@app.command(name="import")
def import_secrets(
    env: str = typer.Argument(..., help="Environment name (e.g., staging, prod)"),
    file: str = typer.Option(..., "--file", "-f", help="Path to import file (.env, .json, .yml)"),
    config: str = typer.Option(
        "./secrets.yml",
        "--config",
        "-c",
        help="Path to secrets config file (default: ./secrets.yml)",
    ),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project name to scope imported secrets"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview what would be imported without making changes"
    ),
    skip_placeholders: bool = typer.Option(
        True,
        "--skip-placeholders/--no-skip-placeholders",
        help="Skip secrets with placeholder values",
    ),
    force: bool = typer.Option(False, "--force", help="Skip confirmation prompt"),
    grant: Optional[List[str]] = typer.Option(
        None, "--grant", "-g", help="Service accounts to grant access"
    ),
):
    """
    Import secrets from a file into Google Secret Manager.

    Supports multiple file formats: .env, .json, .yml/.yaml
    Validates secrets against the schema defined in secrets.yml.

    Examples:
        \\b
        # Import from .env file (assumes ./secrets.yml exists)
        secrets-manager import staging --file .env.staging

        \\b
        # Import from JSON file
        secrets-manager import staging --file secrets.json

        \\b
        # Import from YAML file with custom config
        secrets-manager import prod --file env.yml --config /path/to/secrets.yml

        \\b
        # Dry run to preview changes
        secrets-manager import staging --file .env.staging --dry-run

        \\b
        # Import with project scope
        secrets-manager import staging --file myapp.env --project myapp

        \\b
        # Grant access to service accounts during import
        secrets-manager import staging --file .env --grant bot@project.iam.gserviceaccount.com
    """
    import json
    import yaml

    try:
        # Check if config file exists
        config_path = Path(config)
        if not config_path.exists():
            console.print(f"[red]✗ Error:[/red] Config file '{config}' not found", style="bold red")
            console.print(f"\nPlease ensure secrets.yml exists in the current directory,")
            console.print(f"or specify a custom config path with --config")
            raise typer.Exit(code=1)

        # Set config path
        os.environ["SECRETS_CONFIG_PATH"] = config

        manager = SecretsManager()

        # Check if import file exists
        file_path = Path(file)
        if not file_path.exists():
            console.print(f"[red]✗ Error:[/red] File '{file}' not found", style="bold red")
            raise typer.Exit(code=1)

        # Parse file based on extension
        console.print(f"[bold]Loading secrets from:[/bold] {file}")
        secrets_data = {}

        file_ext = file_path.suffix.lower()

        try:
            if file_ext in [".json"]:
                # Parse JSON file
                with open(file_path, "r") as f:
                    secrets_data = json.load(f)
                    if not isinstance(secrets_data, dict):
                        raise ValueError("JSON file must contain a key-value object")

            elif file_ext in [".yml", ".yaml"]:
                # Parse YAML file
                with open(file_path, "r") as f:
                    secrets_data = yaml.safe_load(f)
                    if not isinstance(secrets_data, dict):
                        raise ValueError("YAML file must contain a key-value mapping")

            elif file_ext in [".env", ""] or file_path.name.startswith(".env"):
                # Parse .env file
                with open(file_path, "r") as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()

                        # Skip empty lines and comments
                        if not line or line.startswith("#"):
                            continue

                        # Parse KEY=VALUE
                        if "=" in line:
                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = value.strip()

                            # Remove quotes if present
                            if value and len(value) >= 2:
                                if (value[0] == '"' and value[-1] == '"') or (
                                    value[0] == "'" and value[-1] == "'"
                                ):
                                    value = value[1:-1]

                            secrets_data[key] = value
                        else:
                            console.print(
                                f"[yellow]⚠[/yellow]  Skipping malformed line {line_num}: {line[:50]}"
                            )
            else:
                console.print(
                    f"[red]✗ Error:[/red] Unsupported file format '{file_ext}'", style="bold red"
                )
                console.print("Supported formats: .env, .json, .yml, .yaml")
                raise typer.Exit(code=1)

        except (json.JSONDecodeError, yaml.YAMLError) as e:
            console.print(f"[red]✗ Error:[/red] Failed to parse {file}: {str(e)}", style="bold red")
            raise typer.Exit(code=1)

        if not secrets_data:
            console.print("[yellow]⚠[/yellow]  No secrets found in file", style="bold yellow")
            raise typer.Exit(code=0)

        # Filter out placeholders if enabled
        placeholder_keywords = ["placeholder", "todo", "changeme", "fixme", "xxx", "replace"]
        filtered_secrets = {}
        skipped_secrets = []

        for key, value in secrets_data.items():
            # Convert value to string if needed
            value_str = str(value) if value is not None else ""

            # Check for empty or placeholder values
            if not value_str or (
                skip_placeholders
                and any(keyword in value_str.lower() for keyword in placeholder_keywords)
            ):
                skipped_secrets.append((key, value_str or "<empty>"))
            else:
                filtered_secrets[key] = value_str

        # Display what will be imported
        console.print(f"\n[bold]Import Summary:[/bold]")
        console.print(f"  Environment: [cyan]{env}[/cyan]")
        if project:
            console.print(f"  Project: [cyan]{project}[/cyan]")
        console.print(f"  Secrets to import: [green]{len(filtered_secrets)}[/green]")

        if skipped_secrets:
            console.print(
                f"  Skipped (placeholders/empty): [yellow]{len(skipped_secrets)}[/yellow]"
            )

        # Show secrets that will be imported
        console.print(f"\n[bold]Secrets to import:[/bold]")
        table = Table()
        table.add_column("Secret Name", style="cyan")
        table.add_column("Value Preview", style="green")

        # Show first 20 secrets
        items_to_show = [item for item in filtered_secrets.items()][:20]
        for key, value in items_to_show:
            masked = f"{value[:10]}..." if len(value) > 10 else value
            table.add_row(key, masked)

        console.print(table)

        if len(filtered_secrets) > 20:
            console.print(f"  ... and {len(filtered_secrets) - 20} more")

        # Show skipped secrets if any
        if skipped_secrets and len(skipped_secrets) <= 10:
            console.print(f"\n[bold yellow]Skipped secrets:[/bold yellow]")
            for key, value in skipped_secrets:
                console.print(f"  • {key}: {value[:50]}")
        elif skipped_secrets:
            console.print(
                f"\n[bold yellow]Skipped {len(skipped_secrets)} placeholder/empty secrets[/bold yellow]"
            )

        # Dry run check
        if dry_run:
            console.print("\n[bold blue]🔍 DRY RUN - No changes will be made[/bold blue]")
            raise typer.Exit(code=0)

        # Confirm import
        if not force:
            console.print()
            confirm = typer.confirm(
                f"Import {len(filtered_secrets)} secrets to {env}"
                + (f".{project}" if project else "")
                + "?"
            )
            if not confirm:
                console.print("Cancelled")
                raise typer.Exit(code=0)

        # Import secrets
        console.print("\n[bold]Importing secrets...[/bold]")
        success_count = 0
        failed_count = 0
        failed_secrets = []

        with console.status("[bold green]Importing secrets..."):
            for secret_name, secret_value in filtered_secrets.items():
                try:
                    result = manager.set_secret(
                        env=env,
                        secret=secret_name,
                        value=secret_value,
                        project=project,
                        grant_to=grant,
                    )
                    success_count += 1
                    # Use the full secret name from the result (includes prefix)
                    full_secret_name = result.get("secret_name", secret_name)
                    console.print(f"  [green]✓[/green] {full_secret_name} ({result['status']})")
                except Exception as e:
                    failed_count += 1
                    failed_secrets.append((secret_name, str(e)))
                    console.print(f"  [red]✗[/red] {secret_name}: {str(e)}")

        # Summary
        console.print("\n[bold]Import Summary:[/bold]")
        console.print(f"  [green]✓[/green] Successfully imported: {success_count}")
        if failed_count > 0:
            console.print(f"  [red]✗[/red] Failed: {failed_count}")

        if failed_secrets:
            console.print("\n[bold red]Failed secrets:[/bold red]")
            for secret_name, error in failed_secrets:
                console.print(f"  • {secret_name}: {error}")

        # Exit with appropriate code
        if failed_count > 0:
            raise typer.Exit(code=1)
        else:
            console.print("\n[green]✅ Import completed successfully![/green]")
            raise typer.Exit(code=0)

    except Exception as e:
        console.print(f"[red]✗ Error:[/red] {str(e)}", style="bold red")
        raise typer.Exit(code=1)


@app.command()
def version():
    """Show version information."""
    from . import __version__

    console.print(f"Botmaro Secrets Manager v{__version__}")
    raise typer.Exit(code=0)


if __name__ == "__main__":
    app()
