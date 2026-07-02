import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.prompt_registry import PromptRegistry


class FakeAppConfigClient:
    def __init__(self, values):
        self._values = values

    def get_configuration_setting(self, *, key, label=None):
        value = self._values[(key, label)]
        return SimpleNamespace(value=value)


class PromptRegistryTests(unittest.TestCase):
    def test_loads_active_prompt_package_from_azure_app_configuration(self):
        agent_id = "test-agent"
        version = "2.0.0"
        manifest = {
            "agent_id": agent_id,
            "package_version": version,
            "model": "gpt-4o",
            "status": "approved",
            "environment": "dev",
            "prompt_files": {
                "system": "system.md",
                "rules": "rules.md",
            },
        }
        registry = PromptRegistry(prompts_root="unused")
        registry._environment = "dev"
        registry._app_config_client = FakeAppConfigClient({
            (f"promptRegistry:{agent_id}:activeVersion", "dev"): version,
            (f"promptRegistry:{agent_id}:{version}:package", "dev"): json.dumps(manifest),
            (f"promptRegistry:{agent_id}:{version}:prompt:system", "dev"): "Azure system prompt",
            (f"promptRegistry:{agent_id}:{version}:prompt:rules", "dev"): "Azure rules prompt",
        })

        package = registry.load_package(agent_id)

        self.assertEqual(package.package_version, version)
        self.assertEqual(package.prompts["system"], "Azure system prompt")
        self.assertEqual(package.prompts["rules"], "Azure rules prompt")

    def test_falls_back_to_local_prompt_files_when_azure_package_is_incomplete(self):
        agent_id = "test-agent"
        version = "1.0.0"
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / agent_id / version
            package_dir.mkdir(parents=True)
            (package_dir / "package.json").write_text(
                json.dumps({
                    "agent_id": agent_id,
                    "package_version": version,
                    "model": "gpt-4o",
                    "status": "approved",
                    "prompt_files": {
                        "system": "system.md",
                    },
                }),
                encoding="utf-8",
            )
            (package_dir / "system.md").write_text(
                "Local system prompt",
                encoding="utf-8",
            )

            registry = PromptRegistry(prompts_root=temp_dir)
            registry._environment = "dev"
            registry._active_versions[agent_id] = version
            registry._app_config_client = FakeAppConfigClient({
                (f"promptRegistry:{agent_id}:{version}:package", "dev"): json.dumps({
                    "agent_id": agent_id,
                    "package_version": version,
                    "model": "gpt-4o",
                    "status": "approved",
                    "prompt_files": {
                        "system": "system.md",
                    },
                }),
            })

            package = registry.load_package(agent_id)

            self.assertEqual(package.prompts["system"], "Local system prompt")


if __name__ == "__main__":
    unittest.main()
