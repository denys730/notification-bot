"""CLI entry points: seeding, and running one checker by hand over the sample events.

uv run python src/commands.py seed [--force]
uv run python src/commands.py run-checker threshold_breach [--brand DEMO] [--row "Threshold Breach 5000 24h"]
uv run python src/commands.py list-checkers --brand DEMO
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import click
from motor.motor_asyncio import AsyncIOMotorClient

from checkers import checker_for_code
from checkers.catalogue import default_rows
from checkers.sample_events import sample_events
from seed import seed_demo_data
from settings import settings
from storage.mongo import MongoStore


def _store() -> tuple[AsyncIOMotorClient, MongoStore]:
    client = AsyncIOMotorClient(settings.MONGO_URI, serverSelectionTimeoutMS=5000)
    return client, MongoStore(client)


@click.group()
def cli() -> None:
    """alert-bot-demo commands."""


@cli.command()
@click.option("--force", is_flag=True, help="Drop and re-create every brand's demo rows")
def seed(force: bool) -> None:
    """Seed demo rows for every configured brand (idempotent unless --force)."""

    async def run() -> None:
        client, store = _store()
        try:
            await store.ensure_indexes(settings.BRANDS)
            for brand, outcome in (await seed_demo_data(store, settings.BRANDS, force=force)).items():
                click.echo(f"{brand}: {outcome}")
        finally:
            client.close()

    asyncio.run(run())


@cli.command("run-checker")
@click.argument("checker_code")
@click.option("--brand", default=None, help="Brand to run as (default: the first configured brand)")
@click.option("--row", "row_name", default=None, help="Catalogue row to use (default: the first row of that code)")
def run_checker(checker_code: str, brand: str | None, row_name: str | None) -> None:
    """Run one checker over the built-in sample events and print the alerts it would raise."""
    brand = (brand or (settings.BRANDS[0] if settings.BRANDS else "DEMO")).upper()
    checker_cls = checker_for_code(checker_code)
    if checker_cls is None:
        raise click.ClickException(f"Unknown checker code '{checker_code}'")
    rows = [row for row in default_rows(brand) if row["checker_code"] == checker_code]
    if row_name:
        rows = [row for row in rows if row["checker_name"] == row_name]
    if not rows:
        raise click.ClickException(
            f"No catalogue row for '{checker_code}'" + (f" named '{row_name}'" if row_name else "")
        )
    now = datetime.now(UTC)
    checker = checker_cls(rows[0], now=now)
    alerts = checker.check(sample_events(now))
    click.echo(f"{rows[0]['checker_name']} ({checker_code}) on {brand}: {len(alerts)} alert(s)")
    for alert in alerts:
        click.echo(json.dumps({"entity_id": alert.entity_id, "text": alert.text, "context": alert.context}, indent=2))


@cli.command("list-checkers")
@click.option("--brand", default=None)
def list_checkers(brand: str | None) -> None:
    """Print the stored checker rows of a brand."""

    async def run() -> None:
        client, store = _store()
        try:
            query = {"brand": brand.upper()} if brand else {}
            async for doc in store.checkers.find(query).sort([("brand", 1), ("checker_name", 1)]):
                flag = "on " if doc.get("enabled") else "off"
                click.echo(
                    f"[{flag}] {doc['brand']:<6} {doc['checker_code']:<18} {doc['checker_name']}  ({doc['_id']})"
                )
        finally:
            client.close()

    asyncio.run(run())


if __name__ == "__main__":
    cli()
