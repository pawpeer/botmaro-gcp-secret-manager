"""Google Secret Manager integration."""

from typing import Optional, List, Dict, Any
from google.cloud import secretmanager
from google.api_core import exceptions


class GSMClient:
    """Wrapper around Google Secret Manager client."""

    def __init__(self, project_id: str):
        """Initialize GSM client for a specific project."""
        self.project_id = project_id
        self.client = secretmanager.SecretManagerServiceClient()
        self.project_path = f"projects/{project_id}"

    def create_secret(self, secret_id: str, replication_policy: str = "automatic") -> bool:
        """
        Create a new secret (without version).

        Args:
            secret_id: The ID of the secret to create
            replication_policy: Replication policy (automatic or user-managed)

        Returns:
            True if created, False if already exists
        """
        try:
            parent = self.project_path
            secret: Dict[str, Any] = {"replication": {"automatic": {}}}

            if replication_policy != "automatic":
                # Allow custom replication policies in the future
                pass

            self.client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": secret_id,
                    "secret": secret,
                }
            )
            return True
        except exceptions.AlreadyExists:
            return False

    def add_secret_version(self, secret_id: str, payload: str) -> str:
        """
        Add a new version to an existing secret.

        Args:
            secret_id: The ID of the secret
            payload: The secret value

        Returns:
            The version name
        """
        parent = f"{self.project_path}/secrets/{secret_id}"

        response = self.client.add_secret_version(
            request={
                "parent": parent,
                "payload": {"data": payload.encode("UTF-8")},
            }
        )

        return response.name

    def get_secret_version(self, secret_id: str, version: str = "latest") -> Optional[str]:
        """
        Get a specific version of a secret.

        Args:
            secret_id: The ID of the secret
            version: Version number or 'latest'

        Returns:
            The secret value or None if not found
        """
        try:
            name = f"{self.project_path}/secrets/{secret_id}/versions/{version}"
            response = self.client.access_secret_version(request={"name": name})
            return response.payload.data.decode("UTF-8")
        except exceptions.NotFound:
            return None
        except exceptions.PermissionDenied as e:
            raise PermissionError(
                f"Permission denied accessing secret '{secret_id}' in project "
                f"'{self.project_id}' ({name}). Grant the caller "
                "roles/secretmanager.secretAccessor on this secret or project."
            ) from e

    def list_secrets(self, filter_str: Optional[str] = None) -> List[str]:
        """
        List all secrets in the project.

        Args:
            filter_str: Optional filter string

        Returns:
            List of secret IDs
        """
        request = {"parent": self.project_path}
        if filter_str:
            request["filter"] = filter_str

        secrets = []
        for secret in self.client.list_secrets(request=request):
            # Extract secret ID from full name
            secret_id = secret.name.split("/")[-1]
            secrets.append(secret_id)

        return secrets

    def delete_secret(self, secret_id: str) -> bool:
        """
        Delete a secret and all its versions.

        Args:
            secret_id: The ID of the secret to delete

        Returns:
            True if deleted, False if not found
        """
        try:
            name = f"{self.project_path}/secrets/{secret_id}"
            self.client.delete_secret(request={"name": name})
            return True
        except exceptions.NotFound:
            return False

    def grant_access(
        self, secret_id: str, member: str, role: str = "roles/secretmanager.secretAccessor"
    ):
        """
        Grant IAM access to a secret.

        Args:
            secret_id: The ID of the secret
            member: The member to grant access to (e.g., 'serviceAccount:sa@project.iam.gserviceaccount.com')
            role: The IAM role to grant
        """
        name = f"{self.project_path}/secrets/{secret_id}"

        policy = self.client.get_iam_policy(request={"resource": name})

        # Check if binding already exists
        binding_exists = False
        for binding in policy.bindings:
            if binding.role == role:
                if member not in binding.members:
                    binding.members.append(member)
                binding_exists = True
                break

        # Create new binding if it doesn't exist
        if not binding_exists:
            from google.iam.v1 import policy_pb2

            new_binding = policy_pb2.Binding(role=role, members=[member])
            policy.bindings.append(new_binding)

        self.client.set_iam_policy(request={"resource": name, "policy": policy})

    def has_access(
        self, secret_id: str, member: str, role: str = "roles/secretmanager.secretAccessor"
    ) -> bool:
        """
        Check if a member has access to a secret.

        Args:
            secret_id: The ID of the secret
            member: The member to check (e.g., 'serviceAccount:sa@project.iam.gserviceaccount.com')
            role: The IAM role to check

        Returns:
            True if the member has the role, False otherwise
        """
        try:
            name = f"{self.project_path}/secrets/{secret_id}"
            policy = self.client.get_iam_policy(request={"resource": name})

            for binding in policy.bindings:
                if binding.role == role and member in binding.members:
                    return True

            return False
        except exceptions.NotFound:
            return False

    def ensure_access(
        self, secret_id: str, member: str, role: str = "roles/secretmanager.secretAccessor"
    ) -> bool:
        """
        Ensure a member has access to a secret (grant if not already granted).

        Args:
            secret_id: The ID of the secret
            member: The member to grant access to (e.g., 'serviceAccount:sa@project.iam.gserviceaccount.com')
            role: The IAM role to grant

        Returns:
            True if access was granted, False if already had access
        """
        if self.has_access(secret_id, member, role):
            return False

        self.grant_access(secret_id, member, role)
        return True

    def ensure_secret(self, secret_id: str, value: str) -> Dict[str, str]:
        """
        Ensure a secret exists with the given value (idempotent).

        Args:
            secret_id: The ID of the secret
            value: The secret value

        Returns:
            Dict with 'status' and 'version'
        """
        # Try to create the secret
        created = self.create_secret(secret_id)

        # Add the version
        version = self.add_secret_version(secret_id, value)

        return {
            "status": "created" if created else "updated",
            "version": version,
            "secret_id": secret_id,
        }
