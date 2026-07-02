# VoxQuery — Voice-Driven Data Analyst

VoxQuery is an enterprise-grade, voice-driven data analyst that enables non-technical stakeholders and executives to query data warehouses (like Snowflake) using natural language speech, and receive instant visualizations and spoken summaries.

## Project Documents

### Active Specifications (Voice Subsystem)
- **Voice Subsystem Engineering Spec**: [engineering-spec.md](./docs/voice-subsystem/engineering-spec.md)
- **Voice Subsystem Interface Contracts**: [interface-contracts.md](./docs/voice-subsystem/interface-contracts.md)

### Active Core Documents
- **Revised MVP Product Requirements Document (PRD)**: [prd.md](./docs/prd.md)

### Archived Core Documents
- **Foundational Architectural Blueprint**: [architecture-blueprint.md](./docs/archive/architecture-blueprint.md)
- **Archived & Historical Documents**: All historical blueprints, PRD versions, and drafts can be found in the [docs/archive/](./docs/archive/) directory.

## Contribution & Review Workflow

To ensure the integrity of the Product Requirements Document (PRD) and core project files, please follow this workflow when proposing revisions or edits:

1. **Create a Revision Branch**:
   If you are making edits or suggesting revisions, work in the dedicated revisions branch or create a new branch from `main`:
   ```bash
   # Switch to the prd-revisions branch
   git checkout prd-revisions
   
   # Or create your own revision branch
   git checkout -b prd-revisions-yourname
   ```

2. **Make and Commit Your Edits**:
   Edit the PRD or relevant files and commit your changes with a clear message:
   ```bash
   git add docs/prd.md
   git commit -m "docs: suggest revisions to section X"
   ```

3. **Push and Open a Pull Request (PR)**:
   Push your branch to GitHub and open a Pull Request against the `main` branch for review:
   ```bash
   git push -u origin prd-revisions-yourname
   ```
