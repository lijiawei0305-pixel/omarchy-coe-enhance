"""Stage QML in a fresh directory to bypass Quattro's component directory cache."""

import hashlib
import json
from pathlib import Path


def version_qml(folder):
    folder = Path(folder)
    widget = (folder / "bar/widget.qml").read_text()
    panel = (folder / "CoePanel.qml").read_bytes()
    revision = hashlib.sha256(widget.encode() + panel).hexdigest()[:16]
    relative = Path("revisions") / ("rev" + revision)
    destination = folder / relative
    (destination / "bar").mkdir(parents=True)
    (destination / "bar/widget.qml").write_text(
        widget.replace("../scripts/coe-bridge.py", "../../../scripts/coe-bridge.py")
    )
    (destination / "CoePanel.qml").write_bytes(panel)
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["entryPoints"]["barWidget"] = str(relative / "bar/widget.qml")
    (folder / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    return revision
