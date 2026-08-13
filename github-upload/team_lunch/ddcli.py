from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_INTENT = (
    "Summary: Help the user's team coordinate a group lunch\n"
    "user prompt/purpose: \"Create a terminal-only team lunch group ordering workflow\""
)


class DDCLIError(RuntimeError):
    """A safe, user-facing dd-cli invocation error."""

    def __init__(self, message: str, *, stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


@dataclass
class DDCLI:
    executable: Optional[str] = None
    intent: str = DEFAULT_INTENT

    def resolve(self) -> str:
        configured = self.executable or os.environ.get("DD_CLI_PATH")
        path = configured or shutil.which("dd-cli")
        if not path:
            raise DDCLIError(
                "dd-cli was not found. Install it, then run 'dd-cli login' before using Team Lunch."
            )
        return path

    def version(self) -> str:
        result = self._run(["--version"], timeout=15)
        return result.stdout.strip()

    def run_json(
        self,
        arguments: Iterable[str],
        *,
        timeout: int = 45,
        include_intent: bool = True,
    ) -> Dict[str, Any]:
        args = ["--json-output", *list(arguments)]
        if include_intent:
            args.extend(["--intent", self.intent])
        result = self._run(args, timeout=timeout)
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DDCLIError(
                "dd-cli returned an unreadable response. Try updating dd-cli.",
                stdout=result.stdout,
                stderr=result.stderr,
            ) from exc
        if not isinstance(value, dict):
            raise DDCLIError("dd-cli returned an unexpected response shape.")
        return value

    def run_text(
        self,
        arguments: Iterable[str],
        *,
        timeout: int = 45,
        include_intent: bool = True,
    ) -> str:
        args = list(arguments)
        if include_intent:
            args.extend(["--intent", self.intent])
        return self._run(args, timeout=timeout).stdout.strip()

    def _run(self, arguments: List[str], *, timeout: int) -> subprocess.CompletedProcess:
        executable = self.resolve()
        try:
            return subprocess.run(
                [executable, *arguments],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise DDCLIError("DoorDash took too long to respond. Nothing was retried.") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            message = "dd-cli could not complete the request."
            if detail:
                message = f"{message} {detail}"
            raise DDCLIError(message, stdout=exc.stdout or "", stderr=exc.stderr or "") from exc


def find_mapping_with_key(value: Any, key: str) -> Optional[Dict[str, Any]]:
    """Find the shallowest mapping containing key in a JSON response envelope."""
    if isinstance(value, dict):
        if key in value:
            return value
        for child in value.values():
            found = find_mapping_with_key(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_mapping_with_key(child, key)
            if found is not None:
                return found
    return None


def response_list(value: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    mapping = find_mapping_with_key(value, key)
    if not mapping or not isinstance(mapping.get(key), list):
        return []
    return [item for item in mapping[key] if isinstance(item, dict)]


def response_value(value: Dict[str, Any], key: str, default: Any = None) -> Any:
    mapping = find_mapping_with_key(value, key)
    return mapping.get(key, default) if mapping else default
