"""Typer CLI for managing datasets."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from app.core.db import SessionLocal, session_scope
from app.core.logging import configure_logging
from app.ingest.importer import ingest_dataset
from app.models import Dataset

console = Console()

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Histone viewer dataset CLI")


@app.callback()
def _main() -> None:
    configure_logging()


@app.command()
def ingest(
    root: Path = typer.Option(..., "--root", "-r", help="Dataset folder, e.g. shuju/MZ...html/"),
    slug: str = typer.Option(..., "--slug", "-s", help="Unique identifier used in URLs."),
    name: str = typer.Option(..., "--name", "-n", help="Human readable name."),
    description: str | None = typer.Option(None, "--description", "-d"),
    keep_existing: bool = typer.Option(False, "--keep-existing", help="Append rather than replace."),
) -> None:
    """Ingest (or re-ingest) a dataset into the database."""
    with session_scope() as session:
        stats = ingest_dataset(
            session,
            root=root,
            slug=slug,
            name=name,
            description=description,
            clear_existing=not keep_existing,
        )
    console.print(f"[green]done[/green]  dataset_id={stats.dataset_id}")
    console.print(
        f"  proteins={stats.proteins}  proteoforms={stats.proteoforms}  prsms={stats.prsms}"
    )


@app.command()
def list_() -> None:
    """List registered datasets."""
    with SessionLocal() as session:
        rows = session.execute(select(Dataset).order_by(Dataset.id)).scalars().all()
    table = Table(title="Datasets")
    table.add_column("id", justify="right")
    table.add_column("slug")
    table.add_column("name")
    table.add_column("source_path")
    for r in rows:
        table.add_row(str(r.id), r.slug, r.name, r.source_path)
    console.print(table)


@app.command()
def drop(slug: str = typer.Argument(..., help="Dataset slug to remove.")) -> None:
    """Delete a dataset and all its rows."""
    with session_scope() as session:
        dataset = session.execute(select(Dataset).where(Dataset.slug == slug)).scalar_one_or_none()
        if dataset is None:
            console.print(f"[yellow]no dataset with slug {slug}[/yellow]")
            return
        session.delete(dataset)
    console.print(f"[red]removed[/red] dataset {slug}")


if __name__ == "__main__":
    app()
