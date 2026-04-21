#!/usr/bin/env python
"""Migrate feature_fixtures_manifest from schema v1 to v2 with candidates."""

import json
from pathlib import Path

def main():
    # Read current v1 manifest
    manifest_path = Path("tests/data/feature_fixtures_manifest.json")
    v1_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Convert to v2 with candidates
    v2_manifest = {
        "schema_version": 2,
        "generated_at_utc": v1_manifest["generated_at_utc"],
        "fixtures": []
    }

    for fixture in v1_manifest["fixtures"]:
        expected_detection = fixture.pop("expected_detection")
        
        # Wrap existing expected_detection as primary candidate
        fixture["candidates"] = [
            {
                "rank": 1,
                "name": "primary",
                "confidence": 0.95,
                "expected_detection": expected_detection
            }
        ]
        v2_manifest["fixtures"].append(fixture)

    # Write v2 manifest
    manifest_path.write_text(json.dumps(v2_manifest, indent=2), encoding="utf-8")
    print(f"✓ Converted {len(v2_manifest['fixtures'])} fixtures to schema v2")
    print("✓ All fixtures now have candidates array")

if __name__ == "__main__":
    main()
