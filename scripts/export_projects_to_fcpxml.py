#!/usr/bin/env python3
"""Export sample projects to FCPXML format."""

import asyncio
import sys
from pathlib import Path

# Add backend src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "apps/backend/src"))

from avid.export import FCPXMLExporter
from avid.models.project import Project

SAMPLE_DIR = Path(__file__).parent.parent / "sample_projects"


async def main():
    exporter = FCPXMLExporter()

    # Find all .avid.json files
    project_files = list(SAMPLE_DIR.glob("*.avid.json"))

    for project_file in project_files:
        print(f"Loading: {project_file.name}")
        project = Project.load(project_file)

        # Export to FCPXML (cuts removed)
        output_path = project_file.with_suffix("").with_suffix(".fcpxml")
        result_path = await exporter.export(project, output_path)
        print(f"  → Exported: {result_path.name}")

        # Export to FCPXML with disabled cuts visible
        output_path_disabled = project_file.with_suffix("").with_suffix(
            ".with_disabled.fcpxml"
        )
        result_path_disabled = await exporter.export(
            project, output_path_disabled, show_disabled_cuts=True
        )
        print(f"  → Exported: {result_path_disabled.name} (with disabled cuts)")

    print(f"\nAll exports saved to: {SAMPLE_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
