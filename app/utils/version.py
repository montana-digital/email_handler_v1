"""Version detection from git tags."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from app.config import PROJECT_ROOT


def get_version_from_git() -> str:
    """Get version from git tags using git describe.
    
    Returns:
        Version string (e.g., "v0.6.0" or "v0.6.0-5-gabc123" for commits after tag)
        Falls back to "dev" if git is not available or not in a git repo
    """
    try:
        # Try to get the latest tag
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        
        if result.returncode == 0 and result.stdout.strip():
            version = result.stdout.strip()
            # Remove 'v' prefix if present for consistency
            if version.startswith("v"):
                return version
            return f"v{version}"
        
        # If no tags exist, try to get commit hash
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        
        if result.returncode == 0 and result.stdout.strip():
            return f"dev-{result.stdout.strip()}"
            
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass
    
    # Fallback to hardcoded version if git is not available
    return "v0.6.4"


def get_app_version(clean: bool = True) -> str:
    """Get the application version.
    
    This is the main function to use throughout the app.
    It returns the version from git tags, or a fallback version.
    
    Args:
        clean: If True, removes "-dirty" suffix for cleaner display. Default True.
    
    Returns:
        Version string (e.g., "v0.6.0")
    """
    version = get_version_from_git()
    if clean and version.endswith("-dirty"):
        # Remove "-dirty" suffix for cleaner UI display
        version = version[:-6]
    return version

