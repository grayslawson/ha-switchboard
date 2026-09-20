"""Stable opaque identifiers shared by the Core adapter and gateway compiler."""

from __future__ import annotations

import hashlib


def opaque_id(namespace: str, value: str, *, length: int = 20) -> str:
    digest = hashlib.sha256(f"{namespace}\0{value}".encode("utf-8")).hexdigest()
    return f"{namespace[:16]}-{digest[:length]}"


def adapter_ref(entity_id: str) -> str:
    """Hash a Core-local entity ID before it enters the gateway snapshot."""

    return opaque_id("adapter", entity_id)


def capability_id(adapter_reference: str, operation: str) -> str:
    """Match the App compiler's stable capability derivation."""

    return opaque_id("capability", f"{adapter_reference}:{operation}")


def routine_capability_id(adapter_reference: str) -> str:
    return opaque_id("capability", f"routine:{adapter_reference}")
