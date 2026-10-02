"""Warrant construction and MCP metadata for the incident workflow."""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass

from tenuo import Exact, Pattern, SigningKey, Warrant, encode_warrant_stack


@dataclass(frozen=True)
class PresentedAuthority:
    chain: tuple[Warrant, ...]
    holder_key: SigningKey

    @property
    def leaf(self) -> Warrant:
        return self.chain[-1]

    def metadata(self, tool: str, arguments: dict[str, object]) -> dict[str, object]:
        encoded = (
            self.leaf.to_base64()
            if len(self.chain) == 1
            else encode_warrant_stack(list(self.chain))
        )
        proof = self.leaf.sign(
            self.holder_key,
            tool,
            arguments,
            int(time.time()),
        )
        return {
            "tenuo": {
                "warrant": encoded,
                "signature": base64.b64encode(bytes(proof)).decode("ascii"),
            }
        }

    def detached(self) -> "PresentedAuthority":
        """Present the delegated leaf without the parent it derives from."""
        return PresentedAuthority((self.leaf,), self.holder_key)


@dataclass(frozen=True)
class DemoAuthority:
    issuer_key: SigningKey
    orchestrator_key: SigningKey
    worker_key: SigningKey
    root: Warrant
    worker: Warrant

    @property
    def orchestrator(self) -> PresentedAuthority:
        return PresentedAuthority((self.root,), self.orchestrator_key)

    @property
    def delegated_worker(self) -> PresentedAuthority:
        return PresentedAuthority((self.root, self.worker), self.worker_key)

    @property
    def issuer_public_hex(self) -> str:
        return self.issuer_key.public_key.to_bytes().hex()


@dataclass(frozen=True)
class RootAuthority:
    """Authority held by the long-running orchestrator."""

    issuer_key: SigningKey
    orchestrator_key: SigningKey
    root: Warrant

    @property
    def issuer_public_hex(self) -> str:
        return self.issuer_key.public_key.to_bytes().hex()


def create_root_authority() -> RootAuthority:
    """Mint the orchestrator's broad, long-lived authority."""
    issuer_key = SigningKey.generate()
    orchestrator_key = SigningKey.generate()

    root = (
        Warrant.mint_builder()
        .capability("read_metrics", service=Exact("checkout"))
        .capability("read_deployment", service=Exact("checkout"))
        .capability(
            "rollback_deployment",
            service=Exact("checkout"),
            deployment=Pattern("*"),
        )
        .holder(orchestrator_key.public_key)
        .ttl(600)
        .mint(issuer_key)
    )

    return RootAuthority(
        issuer_key=issuer_key,
        orchestrator_key=orchestrator_key,
        root=root,
    )


def derive_worker_authority(
    authority: RootAuthority,
    *,
    child_ttl: int = 120,
    worker_key: SigningKey | None = None,
) -> tuple[SigningKey, Warrant, PresentedAuthority]:
    """Derive read-only authority for one worker invocation."""
    worker_key = worker_key or SigningKey.generate()

    worker = (
        authority.root.grant_builder()
        .capability("read_metrics", service=Exact("checkout"))
        .capability("read_deployment", service=Exact("checkout"))
        .holder(worker_key.public_key)
        .ttl(child_ttl)
        .grant(authority.orchestrator_key)
    )

    presented = PresentedAuthority((authority.root, worker), worker_key)
    return worker_key, worker, presented


def create_authority(*, child_ttl: int = 120) -> DemoAuthority:
    """Create a complete authority fixture for deterministic scenarios."""
    root_authority = create_root_authority()
    worker_key, worker, _ = derive_worker_authority(
        root_authority,
        child_ttl=child_ttl,
    )

    return DemoAuthority(
        issuer_key=root_authority.issuer_key,
        orchestrator_key=root_authority.orchestrator_key,
        worker_key=worker_key,
        root=root_authority.root,
        worker=worker,
    )
