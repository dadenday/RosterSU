#!/usr/bin/env python3
"""
Setup script for RosterSU application.
Installs all required dependencies automatically.
"""

import subprocess
import sys

REQUIREMENTS = [
    "python-fasthtml",
    "python-calamine",
    "rapidfuzz",
]


def check_package_installed(package_name):
    """Check if a package is installed."""
    try:
        __import__(package_name.replace("-", "_"))
        return True
    except ImportError:
        return False


def install_dependencies():
    """Install all required dependencies."""
    missing = []
    for package in REQUIREMENTS:
        import_name = package.replace("-", "_")
        if not check_package_installed(import_name):
            missing.append(package)

    if not missing:
        print("✓ All dependencies are already installed.")
        return True

    print("Missing dependencies:")
    for pkg in missing:
        print(f"  - {pkg}")
    print()
    print("Installing missing packages...")

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--upgrade", "-r", "requirements.txt"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        print("\n✓ All dependencies installed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n✗ Failed to install dependencies: {e}", file=sys.stderr)
        print("\nYou can install them manually with:", file=sys.stderr)
        print(f"  pip install -r requirements.txt", file=sys.stderr)
        return False


if __name__ == "__main__":
    success = install_dependencies()
    sys.exit(0 if success else 1)
