"""Main CLI entry point for Smart Butler."""

import click


@click.group()
@click.version_option(version=__import__("butler").__version__, prog_name="butler")
def cli():
    """Smart Butler - Voice-first AI assistant for macOS.

    Processes voice memos and routes notes to Obsidian automatically.
    """
    pass


@cli.command()
def doctor():
    """Run health check and verify dependencies."""
    click.echo("Butler Health Check")
    click.echo("===================")
    click.echo()
    click.echo("Status: Not yet implemented. See Task 3.")


@cli.command()
def process_voice():
    """Trigger voice processing (called by launchd)."""
    click.echo("Processing voice input...")
    click.echo("Status: Not yet implemented.")


@cli.command()
def version():
    """Show version information."""
    from butler import __version__

    click.echo(f"Smart Butler {__version__}")


@cli.command()
def config():
    """Open configuration in default editor (placeholder for TUI)."""
    click.echo("Opening configuration...")
    click.echo("Status: TUI implementation pending (Phase 12).")


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
