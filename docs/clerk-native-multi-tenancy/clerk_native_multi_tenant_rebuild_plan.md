# Clerk-Native Multi-Tenant Rebuild For VoxQuery

## Summary
Rebuild VoxQuery’s identity/provisioning layer around Clerk Organizations as the only tenant model. Use direct Clerk IDs as canonical app IDs: `tenant_id = Clerk org ID` and `user_id = Clerk user ID`. Keep VoxQuery’s data isolation model, but change the identity types feeding it from UUIDs to strings.

This plan targets team/company SaaS, not solo private workspaces.

## Key Changes
- Replace custom `vox_user_id` / `vox_tenant_id` metadata dependency in [backend auth](</C:/Users/satya/Desktop/AI Projects/Voice-Driven Data Analyst - VoxQuery/backend/app/middleware/auth.py>) with Clerk-native token parsing.
- In Clerk mode, require an active organization. Reject tokens without active org context instead of falling back to a personal tenant.
- Parse active org from Clerk token version-aware claims:
  - Prefer v2 compact org claim: `payload["o"]["id"]`, `payload["o"]["rol"]`, `payload["o"]["slg"]`.
  - Keep legacy compatibility for `org_id`, `org_role`, and `org_slug` if present.
- Use `payload["sub"]` as `AuthClaims.user_id`.
- Change `AuthClaims.user_id` and `AuthClaims.tenant_id` from `UUID` to `str`; keep session, turn, conversation, widget IDs as UUIDs.
- Remove role lookup from global `users.role`; derive request role from active org membership role in the Clerk token.

## Schema And Webhooks
- Add a migration replacing UUID identity columns with text IDs:
  - `tenants.id TEXT PRIMARY KEY`
  - `users.id TEXT PRIMARY KEY`
  - all `tenant_id` FKs become `TEXT`
  - all `user_id` FKs become `TEXT`
  - existing local UUID data is preserved as text UUID strings.
- Replace global `users.tenant_id` and `users.role` with membership rows:
  - `users(id, email, created_at, updated_at, deleted_at)`
  - `tenant_memberships(tenant_id, user_id, role, permissions, created_at, updated_at, deleted_at)`
  - composite uniqueness on `(tenant_id, user_id)`.
- Change `user_snowflake_roles` to be per membership with composite key `(tenant_id, user_id)`.
- Rewrite [Clerk webhook handling](</C:/Users/satya/Desktop/AI Projects/Voice-Driven Data Analyst - VoxQuery/backend/app/api/webhooks.py>) to be idempotent and lifecycle-complete:
  - `organization.created`: upsert tenant by Clerk org ID and seed glossary/connection.
  - `organization.updated`: update tenant name/slug.
  - `organization.deleted`: soft-delete tenant, soft-delete memberships, remove or disable tenant connection.
  - `organizationMembership.created`: upsert user and membership.
  - `organizationMembership.updated`: update role/permissions.
  - `organizationMembership.deleted`: soft-delete membership immediately.
  - `user.created` / `user.updated`: upsert user profile only, no tenant creation.
  - `user.deleted`: soft-delete user and memberships.
- Remove outbound PATCH calls to Clerk metadata entirely.

## API And Frontend Behavior
- Keep `/api/session` tenant body optional; if supplied, it must equal the active Clerk org ID in claims.
- Update all tenant-scoped DB queries to bind string `tenant_id` instead of UUID.
- Customer admin routes become active-org scoped:
  - glossary, workspaces, stats, quality views only read/write `claims.tenant_id`.
  - remove arbitrary cross-tenant admin edits from normal customer admin flows.
- Add Clerk organization UI to the signed-in shell:
  - render `<OrganizationSwitcher />` near `UserButton`.
  - block the main VoxQuery app until an active organization exists.
  - show a create/select organization flow for signed-in users with no active org.
- Continue using `getToken()` per request, which is important for correct active-org tokens across browser tabs.

## Test Plan
- Auth tests:
  - accepts Clerk token with v2 `o.id` / `o.rol`.
  - accepts legacy `org_id` / `org_role`.
  - rejects Clerk token with no active org.
  - normalizes `org:admin` and `admin` role shapes.
  - no longer requires `vox_user_id` or `vox_tenant_id`.
- Webhook tests:
  - each org, membership, and user lifecycle event is idempotent.
  - membership deletion immediately removes access.
  - org deletion disables data access without deleting historical turns.
- API tests:
  - `/api/session` uses active org when tenant omitted.
  - mismatched tenant request is rejected.
  - admin glossary/workspace routes are scoped to active tenant.
- Data tests:
  - RAG retrieval, glossary lookup, warehouse connection lookup, sessions, turns, widgets, and audit writes still isolate by `tenant_id`.
- Frontend tests:
  - signed-in user without active org is blocked from starting a session.
  - active org switch causes subsequent requests to use a fresh `getToken()` result.
- Run targeted backend auth/webhook/API tests plus frontend build/test after migration edits.

## Assumptions
- VoxQuery is pre-production or can tolerate a controlled identity migration that preserves existing UUID rows as text IDs.
- Clerk Organizations are enabled for the Clerk instance.
- VoxQuery will not support “personal account as tenant” in Clerk mode; every usable workspace is a Clerk Organization.
- For now, org role `admin` grants customer admin access and all other roles are non-admin.
- Platform-wide operator admin is out of scope for this rebuild unless added later as a separate internal role model.

## Sources
- Clerk Organizations overview: [Clerk docs](https://clerk.com/docs/guides/organizations/overview)
- Clerk session token org claims: [Clerk docs](https://clerk.com/docs/guides/sessions/session-tokens)
- Clerk webhook sync guidance: [Clerk docs](https://clerk.com/docs/guides/development/webhooks/syncing)
