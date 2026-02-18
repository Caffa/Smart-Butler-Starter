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
@click.option("--fix", is_flag=True, help="Auto-download missing models")
def doctor(fix: bool):
    """Run health check and verify dependencies."""
    from butler.cli.doctor import check_dependencies

    success = check_dependencies(fix=fix)
    if not success:
        raise click.ClickException("Health check found issues")


@cli.command()
def process_voice():
    """Trigger voice processing (called by launchd)."""
    import logging
    import os
    from pathlib import Path

    from src.core.plugin_manager import PluginManager
    from src.core.router import SimpleRouter
    from src.core.logging_config import setup_logging
    from src.core.config import get_config

    # Initialize logging using config
    config = get_config()
    logs_dir = os.path.expanduser(config.get("paths.logs_dir", "~/.butler/logs"))
    setup_logging(logs_dir)
    logger = logging.getLogger(__name__)

    # Initialize router to bridge events
    router = SimpleRouter()
    router.start()

    # Load plugins
    plugin_dir = Path(__file__).parent.parent.parent / "plugins"
    manager = PluginManager(plugin_dir)
    manager.load_plugins()

    # Get voice_input plugin
    voice_input = manager.get_plugin("voice_input")
    if not voice_input:
        click.echo("Error: voice_input plugin not found", err=True)
        raise SystemExit(1)

    # Scan and process
    files = voice_input.scan_folder()
    processed = 0
    errors = 0

    for file_path in files:
        if voice_input.process_file(file_path):
            processed += 1
        else:
            errors += 1

    click.echo(f"Processed {processed} file(s), {errors} error(s)")

    # Clean up router
    router.stop()


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
