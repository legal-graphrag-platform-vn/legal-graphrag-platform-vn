"""Safety contract for the disposable Milestone A Neo4j runtime."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit


M3_BOLT_PORT = 7688
M3_CONTAINER = "graphrag-neo4j-m3"
M3_IMAGE = "neo4j:5.26.28-community"
M3_VOLUME = "graphrag-neo4j-m3-data"


class M3RuntimeGuardError(RuntimeError):
    pass


def validate_disposable_uri(uri: str) -> str:
    parsed = urlsplit(uri)
    if parsed.scheme not in {"bolt", "neo4j"}:
        raise M3RuntimeGuardError("M3 Neo4j URI must use bolt:// or neo4j://")
    if parsed.username or parsed.password:
        raise M3RuntimeGuardError("M3 Neo4j URI must not contain credentials")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise M3RuntimeGuardError("M3 Neo4j URI must not contain path, query, or fragment routing")
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise M3RuntimeGuardError("M3 Neo4j URI must target localhost")
    try:
        port = parsed.port
    except ValueError as exc:
        raise M3RuntimeGuardError("M3 Neo4j URI has an invalid port") from exc
    if port != M3_BOLT_PORT:
        raise M3RuntimeGuardError(f"M3 Neo4j URI must explicitly use Bolt port {M3_BOLT_PORT}")
    return f"{parsed.scheme}://{parsed.hostname}:{port}"


def require_integration_opt_in(environment: Mapping[str, str]) -> None:
    if environment.get("RUN_NEO4J_INTEGRATION") != "1":
        raise M3RuntimeGuardError("Neo4j integration requires RUN_NEO4J_INTEGRATION=1")


def require_destructive_opt_in(environment: Mapping[str, str]) -> None:
    if environment.get("RUN_M3_DESTRUCTIVE") != "1":
        raise M3RuntimeGuardError("M3 reset requires RUN_M3_DESTRUCTIVE=1")
    if environment.get("CONFIRM_M3_RESET") != "YES":
        raise M3RuntimeGuardError("M3 reset requires CONFIRM_M3_RESET=YES")
