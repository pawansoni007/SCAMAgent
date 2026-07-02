"""
Prompt package loader.

Loads versioned prompt packages from the local prompts/ folder and resolves
the active package version per agent.

Prompt package layout:
    prompts/<agent_id>/<version>/package.json
    prompts/<agent_id>/<version>/system.md
    prompts/<agent_id>/<version>/context.md
    prompts/<agent_id>/<version>/rules.md
    prompts/<agent_id>/<version>/reasoning.md
    prompts/<agent_id>/<version>/validation.md
    prompts/<agent_id>/<version>/explanation.md
    prompts/<agent_id>/<version>/output.md

Governance prompt types (Prompt Management standard):
    system, context, rules, reasoning, validation, explanation, output.
The Context prompt file defines how runtime ScmEvent / conversation context is
interpreted. Dynamic context values are still injected at runtime.
"""

import os
import json
import logging
from pydantic import BaseModel, Field

_PROMPTS_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "prompts")
)

logger = logging.getLogger(__name__)


class PromptPackage(BaseModel):
    agent_id: str = Field(..., description="Agent this package belongs to")
    package_version: str = Field(..., description="Package version (MAJOR.MINOR.PATCH)")
    model: str = Field(..., description="Model the package was authored for")
    status: str = Field(..., description="Approval status: draft | approved | retired")
    environment: str | None = Field(
        default=None, description="Target environment for the prompt package"
    )
    approved_by: str | None = Field(
        default=None, description="Business or engineering approver"
    )
    approved_on: str | None = Field(
        default=None, description="Approval date for the prompt package"
    )
    prompts: dict[str, str] = Field(
        ...,
        description=(
            "Prompt type → resolved prompt text "
            "(system, context, rules, reasoning, validation, explanation, output)"
        ),
    )

    def build_instructions(self, variables: dict[str, str] | None = None) -> str:
        """
        Combine the prompt sections into a single instruction string,
        substituting tenant-config placeholders like {min_supplier_reliability}.

        Sections are composed in governance order. The context section defines
        how dynamic runtime context (ScmEvent / conversation) should be
        interpreted; the values themselves are still injected at runtime.
        Missing optional sections are simply skipped.
        """
        sections = [
            self.prompts.get("system", ""),
            self.prompts.get("context", ""),
            self.prompts.get("rules", ""),
            self.prompts.get("reasoning", ""),
            self.prompts.get("validation", ""),
            self.prompts.get("explanation", ""),
            self.prompts.get("output", ""),
        ]
        text = "\n\n".join(s.strip() for s in sections if s.strip())
        for key, value in (variables or {}).items():
            text = text.replace("{" + key + "}", str(value))
        return text


class PromptRegistry:
    """
    Azure-backed Prompt Registry with local file fallback.

    Azure App Configuration can manage:
      - active package version per agent/environment
      - package manifest per agent/version/environment
      - prompt section text per agent/version/environment

    Local files remain the development fallback and safe runtime fallback when
    App Configuration is not configured or does not contain a complete package.
    """

    def __init__(self, prompts_root: str = _PROMPTS_ROOT) -> None:
        self._prompts_root = prompts_root
        self._environment = os.getenv("APP_ENVIRONMENT", "dev")
        self._app_config_endpoint = os.getenv("AZURE_APPCONFIG_ENDPOINT")
        self._app_config_client = self._create_app_config_client()
        # Active package version per agent — in production this comes
        # from Azure App Configuration (per environment / tenant).
        self._active_versions: dict[str, str] = {
            "scm-procurement-exception-agent": "1.0.0",
            "scm-buyer-chat-agent": "1.0.0",
        }

    def _create_app_config_client(self):
        """
        Create an Azure App Configuration client when configured.

        Local development can run without App Configuration; the registry then
        falls back to the local _active_versions map. In Azure, the Function App
        managed identity needs App Configuration Data Reader.
        """
        if not self._app_config_endpoint:
            return None

        try:
            from azure.appconfiguration import AzureAppConfigurationClient
            from azure.identity import DefaultAzureCredential

            return AzureAppConfigurationClient(
                base_url=self._app_config_endpoint,
                credential=DefaultAzureCredential(
                    exclude_interactive_browser_credential=True,
                ),
            )
        except Exception as exc:
            # Keep local/dev execution resilient if the SDK is not installed or
            # identity is unavailable; package loading still uses local defaults.
            logger.warning(
                "Azure App Configuration prompt registry unavailable; "
                "using local prompt files. Error: %s",
                exc,
            )
            return None

    def _get_app_config_active_version(self, agent_id: str) -> str | None:
        key = f"promptRegistry:{agent_id}:activeVersion"
        return self._get_app_config_value(key)

    def _get_app_config_value(self, key: str) -> str | None:
        if self._app_config_client is None:
            return None

        for label in (self._environment, None):
            try:
                setting = self._app_config_client.get_configuration_setting(
                    key=key,
                    label=label,
                )
                if setting and setting.value:
                    logger.info(
                        "Loaded prompt registry value from Azure App Configuration "
                        "(key=%s, label=%s)",
                        key,
                        label or "<none>",
                    )
                    return setting.value
            except Exception as exc:
                logger.debug(
                    "Prompt registry value not found in Azure App Configuration "
                    "(key=%s, label=%s, error=%s)",
                    key,
                    label or "<none>",
                    exc,
                )

        return None

    def get_active_version(self, agent_id: str) -> str | None:
        return self._get_app_config_active_version(agent_id) or self._active_versions.get(agent_id)

    def set_active_version(self, agent_id: str, version: str) -> None:
        """Switch the active prompt package (rollback/rollforward)."""
        self._active_versions[agent_id] = version

    def load_package(self, agent_id: str, version: str | None = None) -> PromptPackage:
        """
        Load a prompt package from Azure App Configuration, falling back to disk.

        Args:
            agent_id: The agent whose package to load.
            version: Specific version; defaults to the active version.

        Raises:
            FileNotFoundError: If the package or its files do not exist.
            ValueError: If no active version is registered for the agent.
        """
        resolved_version = version or self.get_active_version(agent_id)
        if resolved_version is None:
            raise ValueError(f"No active prompt package registered for agent '{agent_id}'.")

        azure_package = self._load_package_from_app_config(agent_id, resolved_version)
        if azure_package:
            return azure_package

        return self._load_package_from_disk(agent_id, resolved_version)

    def _load_package_from_app_config(
        self,
        agent_id: str,
        version: str,
    ) -> PromptPackage | None:
        """
        Load prompt package content from Azure App Configuration.

        Expected keys:
          promptRegistry:<agent_id>:<version>:package
          promptRegistry:<agent_id>:<version>:prompt:<prompt_type>

        The package value is the package.json manifest. Prompt text is stored in
        one setting per prompt type so individual sections can be updated and
        audited independently.
        """
        if self._app_config_client is None:
            return None

        manifest_key = f"promptRegistry:{agent_id}:{version}:package"
        manifest_value = self._get_app_config_value(manifest_key)
        if not manifest_value:
            return None

        try:
            manifest = json.loads(manifest_value)
            prompt_types = list((manifest.get("prompt_files") or {}).keys())
            prompt_types.extend(
                prompt_type
                for prompt_type in (manifest.get("prompts") or {}).keys()
                if prompt_type not in prompt_types
            )

            prompts: dict[str, str] = {}
            inline_prompts = manifest.get("prompts") or {}
            for prompt_type in prompt_types:
                prompt_key = f"promptRegistry:{agent_id}:{version}:prompt:{prompt_type}"
                prompt_text = self._get_app_config_value(prompt_key)
                if prompt_text is None:
                    prompt_text = inline_prompts.get(prompt_type)
                if prompt_text is None:
                    raise ValueError(
                        f"Missing Azure prompt setting '{prompt_key}'."
                    )
                prompts[prompt_type] = prompt_text

            logger.info(
                "Loaded prompt package from Azure App Configuration "
                "(agent_id=%s, version=%s, prompt_types=%s)",
                agent_id,
                version,
                sorted(prompts.keys()),
            )

            return PromptPackage(
                agent_id=manifest["agent_id"],
                package_version=manifest["package_version"],
                model=manifest["model"],
                status=manifest["status"],
                environment=manifest.get("environment"),
                approved_by=manifest.get("approved_by"),
                approved_on=manifest.get("approved_on"),
                prompts=prompts,
            )
        except Exception as exc:
            logger.warning(
                "Failed to load prompt package from Azure App Configuration; "
                "falling back to local files (agent_id=%s, version=%s). Error: %s",
                agent_id,
                version,
                exc,
            )
            return None

    def _load_package_from_disk(
        self,
        agent_id: str,
        version: str,
    ) -> PromptPackage:
        package_dir = os.path.join(self._prompts_root, agent_id, version)
        manifest_path = os.path.join(package_dir, "package.json")

        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        prompts: dict[str, str] = {}
        for prompt_type, filename in manifest["prompt_files"].items():
            with open(os.path.join(package_dir, filename), encoding="utf-8") as f:
                prompts[prompt_type] = f.read()

        return PromptPackage(
            agent_id=manifest["agent_id"],
            package_version=manifest["package_version"],
            model=manifest["model"],
            status=manifest["status"],
            environment=manifest.get("environment"),
            approved_by=manifest.get("approved_by"),
            approved_on=manifest.get("approved_on"),
            prompts=prompts,
        )
