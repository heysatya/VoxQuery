# Admin UI Test Plan

## Overview
This test plan covers the newly developed Business Glossary Configuration feature within the VoxQuery `/admin` route. It ensures that the robust state management, responsive UI, and backend persistence are functioning flawlessly.

## Test Cases

### TC01: Initial Dashboard State
- **Action**: Navigate to `http://localhost:3000/admin`.
- **Expected Result**: 
  - The dashboard loads without crashes.
  - The "Business Glossary Configuration" title is visible.
  - A table is rendered showing existing tenant glossaries (or an empty state if none exist).
  - The "+ New Synonym Mapping" button is visible.

### TC02: Live Search Filtering
- **Action**: 
  - Type a non-existent string into the search input.
  - **Expected Result**: Table shows "No matching glossaries found".
  - Type a known Tenant ID (e.g., `default-tenant` or whatever is visible).
  - **Expected Result**: The table immediately filters to show only the matching row.

### TC03: Create New Synonym Mapping (Modal Validation)
- **Action**: 
  - Click "+ New Synonym Mapping".
  - **Expected Result**: A modal opens with "New Synonym Mapping" title.
  - Verify "Tenant ID" input is empty and editable.
  - Verify "Save Configuration" is disabled (since Tenant ID is empty).

### TC04: Add Metric and Table Synonyms (Key-Value Editor)
- **Action**: 
  - In the "New Synonym Mapping" modal, enter `test-tenant-99` as the Tenant ID.
  - In Metric Synonyms, enter Base term: `revenue`, Synonym: `total_sales`. Click the `+` button.
  - **Expected Result**: A chip appears with `revenue -> total_sales`.
  - In Table Synonyms, enter Base term: `users`, Synonym: `accounts`. Click the `+` button.
  - **Expected Result**: A chip appears with `users -> accounts`.

### TC05: Save New Synonym Mapping
- **Action**: 
  - Click "Save Configuration".
  - **Expected Result**: 
    - The modal closes.
    - The dashboard automatically refreshes and displays the new `test-tenant-99` entry in the table.
    - The table shows "1 mappings" or chips for the newly added synonyms.

### TC06: Edit Existing Synonym Mapping
- **Action**: 
  - Find the `test-tenant-99` row and click the "Edit" button.
  - **Expected Result**: 
    - The modal opens with "Edit Synonym Mapping" title.
    - Tenant ID input is disabled.
    - The previously added Metric and Table synonyms are rendered as chips in the UI.
  - Click the 'X' button on the `revenue` metric synonym chip to remove it.
  - Add a new metric synonym: Base term: `cost`, Synonym: `expenses`. Click `+`.
  - Click "Save Configuration".
  - **Expected Result**: 
    - The modal closes.
    - Dashboard refreshes.
    - `test-tenant-99` row is updated with the new mappings.
