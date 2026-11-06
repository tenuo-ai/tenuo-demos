"""MCP transport adapter that binds Tenuo proof to each finalized tool call."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tenuo import Authorizer, PublicKey
from tenuo.cli import check_receipt_claims
from tenuo.mcp import SecureMCPClient
from tenuo_core import decode_warrant_stack_base64, verify_receipt

from .authority import PresentedAuthority


@dataclass(frozen=True)
class ToolOutcome:
    status: Literal["allowed", "denied", "error"]
    text: str
    error: str | None = None

    @property
    def allowed(self) -> bool:
        return self.status == "allowed"

    @property
    def denied(self) -> bool:
        return self.status == "denied"


def _content_text(result: object) -> str:
    blocks = getattr(result, "content", []) or []
    return "".join(getattr(block, "text", str(block)) for block in blocks)


@dataclass(frozen=True)
class VerifiedDenial:
    wire: str
    signer_hex: str
    decision_code: str


class OperationsMCP:
    def __init__(
        self,
        *,
        issuer_public_hex: str,
        state_path: Path,
        receipt_path: Path | None = None,
        quiet: bool = False,
    ) -> None:
        # The MCP server needs process/runtime configuration, not the agent's
        # downstream credentials (notably OPENAI_API_KEY).
        inherited_names = (
            "HOME",
            "LANG",
            "LC_ALL",
            "PATH",
            "PYTHONPATH",
            "SSL_CERT_DIR",
            "SSL_CERT_FILE",
            "TMPDIR",
            "VIRTUAL_ENV",
        )
        self._receipt_path = receipt_path or state_path.with_suffix(".receipts")
        # The server creates its own signing key and publishes only the public
        # half here, so the agent side can't sign receipts.
        self._enforcement_key_path = self._receipt_path.with_suffix(".enforcement-key")
        env = {
            **{name: os.environ[name] for name in inherited_names if name in os.environ},
            "TENUO_DEMO_ISSUER_PUBLIC_KEY": issuer_public_hex,
            "TENUO_DEMO_STATE_PATH": str(state_path),
            "TENUO_DEMO_ENFORCEMENT_KEY_PATH": str(self._enforcement_key_path),
            "TENUO_DEMO_RECEIPT_PATH": str(self._receipt_path),
        }
        if quiet:
            env["TENUO_DEMO_QUIET"] = "1"
        self._client = SecureMCPClient(
            command=sys.executable,
            args=["-m", "incident_demo.ops_server"],
            env=env,
            inject_warrant=False,
        )

    async def __aenter__(self) -> "OperationsMCP":
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._client.__aexit__(exc_type, exc, tb)

    async def call(
        self,
        authority: PresentedAuthority,
        tool: str,
        arguments: dict[str, object],
    ) -> ToolOutcome:
        if self._client.session is None:
            raise RuntimeError("MCP client is not connected")
        result = await self._client.session.call_tool(
            tool,
            arguments,
            meta=authority.metadata(tool, arguments),
        )
        text = _content_text(result)
        # MCP SDK v2 uses snake_case; retain a fallback for v1 because Tenuo
        # 0.3 supports both generations of the SDK.
        is_error = getattr(result, "is_error", None)
        if is_error is None:
            is_error = getattr(result, "isError", False)
        is_error = bool(is_error)
        structured = getattr(result, "structured_content", None)
        if structured is None:
            structured = getattr(result, "structuredContent", None)
        structured = structured or {}
        tenuo = structured.get("tenuo", {}) if isinstance(structured, dict) else {}
        is_denial = is_error and isinstance(tenuo, dict) and bool(tenuo)
        if not is_error:
            return ToolOutcome(status="allowed", text=text)

        error = tenuo.get("message") if is_denial else None
        error = error or text or "MCP tool call failed"
        return ToolOutcome(
            status="denied" if is_denial else "error",
            text=text,
            error=error,
        )

    def verify_denial_receipt(
        self,
        tool: str,
        arguments: dict[str, object],
        *,
        trusted_root_hex: str,
        decision_code: str,
    ) -> VerifiedDenial:
        """Verify the enforcement point's signed denial of this exact call."""
        signer_hex = self._enforcement_key_path.read_text(encoding="utf-8").strip()
        for wire in reversed(self._receipt_path.read_text(encoding="utf-8").splitlines()):
            receipt = verify_receipt(wire)
            if receipt.action != tool or receipt.outcome != "deny":
                continue
            if receipt.decision_code != decision_code:
                raise AssertionError(
                    f"expected denial {decision_code}, got {receipt.decision_code}"
                )
            claims, _ = check_receipt_claims(
                receipt,
                roots=[trusted_root_hex],
                authorizers=[signer_hex],
                args=arguments,
            )
            problems = [claim for claim in claims if claim[1] in {"fail", "warn"}]
            if problems:
                raise AssertionError(f"denial receipt claims failed: {problems}")
            # For a denial, the claim above only reports a broken chain.
            Authorizer(trusted_roots=[PublicKey.from_bytes(bytes.fromhex(trusted_root_hex))]).verify_chain(
                decode_warrant_stack_base64(receipt.warrant_chain),
                as_of=receipt.timestamp,
            )
            return VerifiedDenial(
                wire=wire,
                signer_hex=signer_hex,
                decision_code=receipt.decision_code,
            )
        raise AssertionError(f"no signed denial receipt found for {tool}")
