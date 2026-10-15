#!/usr/bin/env python3
"""Check every pinned PyPI and npm package in a lock file against OSV.

Usage:
    python3 scripts/check_vulns.py <lock-file> [<lock-file> ...]

Supported lock files (detected by file name):
    uv.lock              PyPI packages (TOML)
    package-lock.json    npm packages (JSON, lockfileVersion 2 or 3)

For each unique (ecosystem, name, version) it POSTs to the OSV query API and
collects advisories. Prints a table. Standard library only.

Exit codes:
    0  no advisories found
    1  at least one advisory found
    2  usage, parse, or network error (the check did not complete)
"""

import json
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

OSV_QUERY_URL = "https://api.osv.dev/v1/query"
REQUEST_TIMEOUT_SECONDS = 30

EXIT_CLEAN = 0
EXIT_ADVISORY = 1
EXIT_ERROR = 2


def packages_from_uv_lock(path):
    """Return (registry packages, skipped descriptions) from a uv.lock file."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    found = set()
    skipped = []
    for pkg in data.get("package", []):
        name = pkg.get("name")
        version = pkg.get("version")
        source = pkg.get("source", {})
        if "registry" in source:
            if name and version:
                found.add(("PyPI", name, version))
        elif "editable" in source or "virtual" in source:
            continue  # the project itself, not a dependency
        else:
            skipped.append(f"{name} ({', '.join(source) or 'no source'})")
    return found, skipped


def packages_from_package_lock(path):
    """Return (npm packages, skipped descriptions) from a package-lock.json file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    lock_version = data.get("lockfileVersion")
    if lock_version not in (2, 3):
        raise ValueError(
            f"unsupported lockfileVersion {lock_version!r} in {path}; expected 2 or 3"
        )
    found = set()
    skipped = []
    for key, entry in data.get("packages", {}).items():
        if "node_modules/" not in key:
            continue  # the root project and workspace folders
        if entry.get("link") or "version" not in entry:
            skipped.append(key)
            continue
        name = key.rsplit("node_modules/", 1)[-1]
        found.add(("npm", name, entry["version"]))
    return found, skipped


def load_packages(path):
    if path.name == "uv.lock":
        return packages_from_uv_lock(path)
    if path.name == "package-lock.json":
        return packages_from_package_lock(path)
    raise ValueError(
        f"unrecognised lock file {path}; expected a file named uv.lock or package-lock.json"
    )


def query_osv(ecosystem, name, version):
    """Return the advisory IDs OSV reports for one package version, across pages."""
    body = {"package": {"name": name, "ecosystem": ecosystem}, "version": version}
    advisory_ids = []
    while True:
        request = urllib.request.Request(
            OSV_QUERY_URL,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
        advisory_ids.extend(vuln.get("id", "unknown") for vuln in result.get("vulns", []))
        page_token = result.get("next_page_token")
        if not page_token:
            return advisory_ids
        body["page_token"] = page_token


def print_table(results):
    headers = ("ECOSYSTEM", "PACKAGE", "VERSION", "ADVISORIES", "IDS")
    rows = [
        (ecosystem, name, version, str(len(ids)), ", ".join(ids) or "-")
        for ecosystem, name, version, ids in results
    ]
    widths = [max(len(cell) for cell in column) for column in zip(headers, *rows)]

    def render(cells):
        padded = [f"{cell:<{width}}" for cell, width in zip(cells[:-1], widths)]
        return "  ".join(padded + [cells[-1]]).rstrip()

    print(render(headers))
    print(render(tuple("-" * width for width in widths)))
    for row in rows:
        print(render(row))


def main(argv):
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return EXIT_ERROR

    packages = set()
    try:
        for arg in argv:
            found, skipped = load_packages(Path(arg))
            packages |= found
            if skipped:
                print(
                    f"note: {arg}: {len(skipped)} non-registry entries not checked: "
                    + ", ".join(skipped),
                    file=sys.stderr,
                )
    except (OSError, ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if not packages:
        print("error: no pinned registry packages found; nothing was checked", file=sys.stderr)
        return EXIT_ERROR

    results = []
    try:
        for ecosystem, name, version in sorted(packages):
            results.append((ecosystem, name, version, query_osv(ecosystem, name, version)))
    except (OSError, ValueError) as exc:
        print(f"error: OSV query failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print_table(results)
    flagged = [row for row in results if row[3]]
    print()
    print(f"checked {len(results)} package versions, {len(flagged)} with advisories")
    return EXIT_ADVISORY if flagged else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
