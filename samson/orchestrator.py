#!/usr/bin/env python3
"""Samson SBM production orchestrator entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from uuid import UUID, uuid4

from samson.core.config import get_settings
from samson.core.database import Database
from samson.rag.rag_oracle import RagOracle
from samson.rag.schemas import RetrieveContextRequest
from samson.redteam.orchestrator_hooks import SamsonRedTeamHooks
from samson.redteam.schemas import (
    FinancialGuardrailDeployRequest,
    GarakScanRequest,
    PyRITRiskRequest,
)

logging.basicConfig(
    level=logging.INFO,
    format="[Samson] %(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("samson.orchestrator")


def cmd_migrate(_: argparse.Namespace) -> int:
    settings = get_settings()
    db = Database(settings)
    migration_dir = Path(__file__).resolve().parent / "migrations"
    db.ensure_schema(
        [
            str(migration_dir / "001_schema.sql"),
            str(migration_dir / "002_adversary_emulation.sql"),
            str(migration_dir / "003_guardrail_proxy.sql"),
        ]
    )
    logger.info("Schema migration applied")
    return 0


def cmd_health(_: argparse.Namespace) -> int:
    settings = get_settings()
    db = Database(settings)
    hooks = SamsonRedTeamHooks(settings)
    rag = RagOracle(settings)
    try:
        db_status = db.health_check()
        ollama = rag._ollama.health_check()  # noqa: SLF001
        print(json.dumps({"database": db_status, "ollama": {"models": len(ollama.get("models", []))}}, indent=2))
        return 0
    except Exception as exc:
        logger.error("Health check failed: %s", exc)
        return 1
    finally:
        hooks.close()
        rag.close()


def cmd_garak_scan(args: argparse.Namespace) -> int:
    settings = get_settings()
    hooks = SamsonRedTeamHooks(settings)
    try:
        result = hooks.scan_model_health(
            GarakScanRequest(
                request_id=uuid4(),
                model_endpoint=str(settings.ollama_base_url),
                model_name=args.model,
                probe_suite=args.suite,
                environment=settings.environment,
                triggered_by="manual",
            )
        )
        print(result.model_dump_json(indent=2))
        return 0
    finally:
        hooks.close()


def cmd_rag_retrieve(args: argparse.Namespace) -> int:
    settings = get_settings()
    rag = RagOracle(settings)
    try:
        response = rag.retrieve_context(
            RetrieveContextRequest(
                request_id=uuid4(),
                query=args.query,
                environment=settings.environment,
                project=settings.project,
                operator_id=args.operator,
                top_k=args.top_k,
            )
        )
        print(response.model_dump_json(indent=2))
        return 0
    finally:
        rag.close()


def cmd_pyrit_eval(args: argparse.Namespace) -> int:
    settings = get_settings()
    hooks = SamsonRedTeamHooks(settings)
    try:
        draft = json.loads(Path(args.scenario_file).read_text(encoding="utf-8"))
        result = hooks.evaluate_scenario_risk(
            PyRITRiskRequest(
                request_id=uuid4(),
                scenario_id=args.scenario_id,
                scenario_draft=draft,
                environment=settings.environment,
                operator_id=args.operator,
            )
        )
        print(result.model_dump_json(indent=2))
        return 0 if not result.blocked else 2
    finally:
        hooks.close()


def cmd_guardrail_deploy(args: argparse.Namespace) -> int:
    hooks = SamsonRedTeamHooks(get_settings())

    async def _run() -> int:
        try:
            result = await hooks.deploy_financial_guardrail_from_execution(
                FinancialGuardrailDeployRequest(
                    request_id=uuid4(),
                    execution_id=UUID(args.execution_id),
                    operator_id=args.operator,
                    run_id=UUID(args.run_id) if args.run_id else None,
                    policy_profile=args.profile,
                    upstream_base_url=args.upstream,
                )
            )
            print(result.model_dump_json(indent=2))
            return 0
        finally:
            await hooks._guardrail_deployer.close()  # noqa: SLF001
            hooks.close()

    return asyncio.run(_run())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Samson SBM orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    migrate = sub.add_parser("migrate", help="Apply database schema migrations")
    migrate.set_defaults(func=cmd_migrate)

    health = sub.add_parser("health", help="Check database and Ollama connectivity")
    health.set_defaults(func=cmd_health)

    garak = sub.add_parser("garak-scan", help="Run Garak model health scan")
    garak.add_argument("--model", default=get_settings().ollama_chat_model)
    garak.add_argument("--suite", choices=["full", "fast", "custom"], default="fast")
    garak.set_defaults(func=cmd_garak_scan)

    rag = sub.add_parser("rag-retrieve", help="Retrieve RAG context")
    rag.add_argument("--query", required=True)
    rag.add_argument("--operator", default="operator-alpha")
    rag.add_argument("--top-k", type=int, default=8)
    rag.set_defaults(func=cmd_rag_retrieve)

    pyrit = sub.add_parser("pyrit-eval", help="Evaluate scenario risk with PyRIT")
    pyrit.add_argument("--scenario-id", required=True)
    pyrit.add_argument("--scenario-file", required=True)
    pyrit.add_argument("--operator", default="operator-alpha")
    pyrit.set_defaults(func=cmd_pyrit_eval)

    guardrail = sub.add_parser("guardrail-deploy", help="Deploy financial guardrail proxy from emulation result")
    guardrail.add_argument("--execution-id", required=True)
    guardrail.add_argument("--operator", default="operator-alpha")
    guardrail.add_argument("--run-id", default=None)
    guardrail.add_argument("--profile", choices=["strict", "balanced", "permissive"], default="strict")
    guardrail.add_argument("--upstream", default=None)
    guardrail.set_defaults(func=cmd_guardrail_deploy)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
