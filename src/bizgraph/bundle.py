"""Download and cache the release bundle shared by the CLI and Streamlit demo."""

from __future__ import annotations

import os
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from bizgraph.config import REPO_ROOT

DEFAULT_BUNDLE_URL = (
    "https://github.com/kiennguyen16/Business_graph/releases/download/demo-bundle-v4/demo_bundle.tar.gz"
)


def demo_bundle_dir() -> Path:
    return Path(os.environ.get("BIZGRAPH_BUNDLE_DIR") or REPO_ROOT / "demo" / "bundle")


def ensure_demo_bundle(*, fallback_url: str = DEFAULT_BUNDLE_URL) -> Path:
    """Return the cached database, downloading the release assets if needed."""
    target = demo_bundle_dir().resolve()
    db = target / "demo.duckdb"
    if db.is_file():
        return db

    url = os.environ.get("BIZGRAPH_BUNDLE_URL") or fallback_url
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        staging = Path(tmp)
        archive = staging / "bundle.tar.gz"
        urllib.request.urlretrieve(url, archive)
        with tarfile.open(archive) as tar:
            # Release assets are regular files and directories. Refuse links and devices.
            members = [member for member in tar.getmembers() if member.isfile() or member.isdir()]
            tar.extractall(staging, members=members, filter="data")
        bundle = staging / "bundle"
        staged_db = bundle / db.name
        if not staged_db.is_file():
            raise RuntimeError(f"{url} did not contain bundle/demo.duckdb")
        for asset in bundle.rglob("*"):
            if asset.is_file() and asset != staged_db:
                destination = target / asset.relative_to(bundle)
                destination.parent.mkdir(parents=True, exist_ok=True)
                asset.replace(destination)
        # The database is the cache marker. Publish it after all companion assets.
        target.mkdir(exist_ok=True)
        if not db.is_file():
            try:
                staged_db.replace(db)
            except PermissionError:
                if not db.is_file():
                    raise
    return db
