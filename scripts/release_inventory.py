"""Record the dependencies and license metadata of an installed release candidate."""

import argparse
import json
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path


def record(directory):
    directory.mkdir(parents=True, exist_ok=True)
    packages = []
    for distribution in metadata.distributions():
        fields = distribution.metadata
        name = fields["Name"]
        if name.lower() == "tradelang":
            continue
        packages.append(
            {
                "name": name,
                "version": distribution.version,
                "license_expression": fields.get("License-Expression"),
                "license_classifiers": [
                    item
                    for item in (fields.get_all("Classifier") or [])
                    if item.startswith("License ::")
                ],
                "license_text": fields.get("License"),
                "license_files": fields.get_all("License-File") or [],
            }
        )
    packages.sort(key=lambda p: p["name"].lower())
    if not packages:
        raise ValueError(
            "Expected an installed candidate environment with dependencies"
        )
    (directory / "requirements.txt").write_text(
        "".join(f"{p['name']}=={p['version']}\n" for p in packages), encoding="utf-8"
    )
    (directory / "licenses.json").write_text(
        json.dumps(
            {"recorded_at": datetime.now(UTC).isoformat(), "packages": packages},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    record(parser.parse_args().directory)
