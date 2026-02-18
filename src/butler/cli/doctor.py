"""Doctor module - System health checker for Smart Butler.

Checks dependencies, downloads models, and reports system status
with clear emoji indicators.
"""

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import psutil


class Status(Enum):
    """Health check status indicators."""

    OK = "✓"
    WARNING = "⚠"
    ERROR = "✗"
    INFO = "ℹ"


@dataclass
class CheckResult:
    """Result of a single health check."""

    name: str
    status: Status
    message: str
    details: Optional[str] = None


def check_python_version() -> CheckResult:
    """Check if Python version is 3.10+."""
    version = platform.python_version()
    major, minor, _ = version.split(".")

    if int(major) >= 3 and int(minor) >= 10:
        return CheckResult(name="Python", status=Status.OK, message=version)
    else:
        return CheckResult(
            name="Python", status=Status.ERROR, message=version, details="Python 3.10+ required"
        )


def check_macos_version() -> CheckResult:
    """Check if macOS version is 14.0+ (for Apple Silicon features)."""
    if platform.system() != "Darwin":
        return CheckResult(
            name="macOS", status=Status.ERROR, message="Not macOS", details="Butler requires macOS"
        )

    try:
        version = platform.mac_ver()[0]
        major, minor, _ = version.split(".")

        if int(major) >= 14:
            return CheckResult(name="macOS", status=Status.OK, message=version)
        else:
            return CheckResult(
                name="macOS",
                status=Status.WARNING,
                message=version,
                details="macOS 14.0+ recommended for full Apple Silicon features",
            )
    except Exception as e:
        return CheckResult(name="macOS", status=Status.ERROR, message="Unknown", details=str(e))


def check_ollama() -> CheckResult:
    """Check if Ollama is installed and running."""
    try:
        result = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=5)

        if result.returncode == 0:
            version = result.stdout.strip().split()[-1] if result.stdout else "installed"

            # Also check if Ollama service is running
            try:
                subprocess.run(["pgrep", "-x", "ollama"], capture_output=True, timeout=2)
                return CheckResult(name="Ollama", status=Status.OK, message=version)
            except subprocess.TimeoutExpired:
                return CheckResult(
                    name="Ollama",
                    status=Status.WARNING,
                    message=version,
                    details="Installed but service not running. Start with: ollama serve",
                )
        else:
            return CheckResult(
                name="Ollama",
                status=Status.ERROR,
                message="Not installed",
                details="Install from: https://ollama.com/download",
            )
    except FileNotFoundError:
        return CheckResult(
            name="Ollama",
            status=Status.ERROR,
            message="Not installed",
            details="Install from: https://ollama.com/download",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name="Ollama", status=Status.ERROR, message="Timeout", details="Ollama check timed out"
        )


def check_model(model_name: str) -> CheckResult:
    """Check if a specific model is downloaded."""
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            if model_name in result.stdout:
                return CheckResult(
                    name=f"Model {model_name}", status=Status.OK, message="Downloaded"
                )
            else:
                return CheckResult(
                    name=f"Model {model_name}",
                    status=Status.WARNING,
                    message="Not downloaded",
                    details=f"Run: ollama pull {model_name}",
                )
        else:
            return CheckResult(
                name=f"Model {model_name}",
                status=Status.ERROR,
                message="Cannot check",
                details="Ollama list command failed",
            )
    except FileNotFoundError:
        return CheckResult(
            name=f"Model {model_name}",
            status=Status.ERROR,
            message="Ollama not found",
            details="Cannot check models without Ollama",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name=f"Model {model_name}",
            status=Status.ERROR,
            message="Timeout",
            details="Model check timed out",
        )


def check_parakeet() -> CheckResult:
    """Check if parakeet-mlx can be imported (macOS only)."""
    try:
        import parakeet

        return CheckResult(name="parakeet-mlx", status=Status.OK, message="Available")
    except ImportError:
        return CheckResult(
            name="parakeet-mlx",
            status=Status.WARNING,
            message="Not installed",
            details="Install with: pip install parakeet-mlx (macOS only)",
        )


def check_sqlite() -> CheckResult:
    """Check if SQLite is available."""
    try:
        import sqlite3

        version = sqlite3.sqlite_version
        return CheckResult(name="SQLite", status=Status.OK, message=version)
    except ImportError:
        return CheckResult(
            name="SQLite",
            status=Status.ERROR,
            message="Not available",
            details="SQLite is required for memory storage",
        )


def check_disk_space() -> CheckResult:
    """Check available disk space (>1GB recommended)."""
    try:
        home = os.path.expanduser("~")
        stat = shutil.disk_usage(home)
        free_gb = stat.free / (1024**3)

        if free_gb >= 5:
            return CheckResult(name="Disk space", status=Status.OK, message=f"{free_gb:.1f}GB free")
        elif free_gb >= 1:
            return CheckResult(
                name="Disk space",
                status=Status.WARNING,
                message=f"{free_gb:.1f}GB free",
                details="Recommend 5GB+ for AI models",
            )
        else:
            return CheckResult(
                name="Disk space",
                status=Status.ERROR,
                message=f"{free_gb:.1f}GB free",
                details="Need at least 1GB free",
            )
    except Exception as e:
        return CheckResult(
            name="Disk space", status=Status.WARNING, message="Unknown", details=str(e)
        )


def check_write_permissions() -> CheckResult:
    """Check if we can write to ~/.butler/."""
    butler_home = os.path.expanduser("~/.butler")

    try:
        os.makedirs(butler_home, exist_ok=True)
        test_file = os.path.join(butler_home, ".write_test")

        with open(test_file, "w") as f:
            f.write("test")

        os.remove(test_file)

        return CheckResult(name="Write permissions", status=Status.OK, message="OK")
    except Exception as e:
        return CheckResult(
            name="Write permissions", status=Status.ERROR, message="Failed", details=str(e)
        )


def check_chromadb() -> CheckResult:
    """Check if ChromaDB is available."""
    try:
        import chromadb

        version = chromadb.__version__
        return CheckResult(name="ChromaDB", status=Status.OK, message=version)
    except ImportError:
        return CheckResult(
            name="ChromaDB",
            status=Status.ERROR,
            message="Not installed",
            details="Required for vector memory",
        )


def download_model(model_name: str) -> bool:
    """Download a model using Ollama."""
    print(f"  Downloading {model_name}...")

    try:
        result = subprocess.run(
            ["ollama", "pull", model_name],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes timeout
        )

        if result.returncode == 0:
            print(f"  ✓ {model_name} downloaded successfully")
            return True
        else:
            print(f"  ✗ Failed to download {model_name}: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print(f"  ✗ Timeout downloading {model_name}")
        return False
    except FileNotFoundError:
        print(f"  ✗ Ollama not found")
        return False


def run_health_check(fix: bool = False) -> list[CheckResult]:
    """Run all health checks.

    Args:
        fix: If True, attempt to download missing models.

    Returns:
        List of check results.
    """
    results = []

    # System checks
    results.append(check_python_version())
    results.append(check_macos_version())
    results.append(check_disk_space())
    results.append(check_write_permissions())

    # Dependency checks
    results.append(check_ollama())
    results.append(check_model("llama3.1:8b"))
    results.append(check_model("nomic-embed-text"))
    results.append(check_parakeet())
    results.append(check_sqlite())
    results.append(check_chromadb())

    # Auto-fix if requested
    if fix:
        print("\nAuto-fixing issues...")
        print()

        # Check which models need downloading
        for result in results:
            if result.name.startswith("Model ") and result.status == Status.WARNING:
                model_name = result.name.replace("Model ", "")
                if download_model(model_name):
                    # Update the result
                    result.status = Status.OK
                    result.message = "Downloaded"
                    result.details = None

        print()

    return results


def print_results(results: list[CheckResult]) -> None:
    """Print health check results in a formatted table."""
    print()
    print("Butler Health Check")
    print("===================")
    print()

    for result in results:
        print(f"{result.status.value} {result.name}: {result.message}")
        if result.details:
            print(f"    {result.details}")

    print()

    # Overall status
    errors = sum(1 for r in results if r.status == Status.ERROR)
    warnings = sum(1 for r in results if r.status == Status.WARNING)

    if errors == 0 and warnings == 0:
        print("Status: Ready to go! 🎩")
    elif errors == 0:
        print(f"Status: Ready with {warnings} warning(s) ⚠")
    else:
        print(f"Status: {errors} error(s), {warnings} warning(s) - needs attention ✗")

    print()


def check_dependencies(fix: bool = False) -> bool:
    """Main entry point for doctor command.

    Args:
        fix: If True, attempt to fix issues automatically.

    Returns:
        True if all critical checks pass, False otherwise.
    """
    results = run_health_check(fix=fix)
    print_results(results)

    # Check if any errors remain
    errors = sum(1 for r in results if r.status == Status.ERROR)
    return errors == 0


if __name__ == "__main__":
    import sys

    fix = "--fix" in sys.argv
    success = check_dependencies(fix=fix)
    sys.exit(0 if success else 1)
