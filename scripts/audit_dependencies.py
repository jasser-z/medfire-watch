"""Audit installed package versions against OSV without skipping CUDA local versions.

Only distribution names and public version numbers are sent to the provider.
Advisory records can have aliases; their count is not a count of unique CVEs.
"""

from __future__ import annotations

from importlib.metadata import distributions

import requests


def main() -> None:
    packages = sorted(
        (dist.metadata["Name"], dist.version.split("+")[0]) for dist in distributions() if dist.metadata["Name"]
    )
    findings = 0
    for offset in range(0, len(packages), 100):
        batch = packages[offset : offset + 100]
        try:
            response = requests.post(
                "https://api.osv.dev/v1/querybatch",
                json={
                    "queries": [
                        {"package": {"name": name, "ecosystem": "PyPI"}, "version": version} for name, version in batch
                    ]
                },
                timeout=(10, 60),
            )
            response.raise_for_status()
            results = response.json()["results"]
            if len(results) != len(batch):
                raise ValueError("Incomplete OSV response")
        except (requests.RequestException, ValueError, KeyError):
            raise SystemExit("Dependency audit unavailable: OSV request failed or returned invalid data.") from None
        for (name, version), result in zip(batch, results):
            advisories = result.get("vulns", [])
            if advisories:
                findings += 1
                print(f"{name} {version}: {', '.join(item['id'] for item in advisories)}")
    print(f"Audited {len(packages)} installed distributions; {findings} package(s) with advisory records.")
    raise SystemExit(1 if findings else 0)


if __name__ == "__main__":
    main()
