# VoxQuery Clerk Auth Setup

## Required JWT Claims

The backend validates Clerk JWTs and maps them into the existing VoxQuery session contract.
The token must include these custom UUID claims:

- `vox_user_id`
- `vox_tenant_id`

These claims are required because VoxQuery session, Redis, and app metadata contracts currently use UUID user and tenant IDs.

## Clerk Dashboard Setup

Add custom session claims in the Clerk dashboard using the UUIDs stored on the Clerk user:

```json
{
  "vox_user_id": "{{user.public_metadata.vox_user_id}}",
  "vox_tenant_id": "{{user.public_metadata.vox_tenant_id}}"
}
```

If either claim is missing or malformed, the backend rejects the request with `auth_invalid`.
After changing Session Token claims or user metadata, sign out and sign back in so Clerk
issues a fresh token with the updated claims.

## Environment Variables

Required when `AUTH_MODE=clerk`:

```env
AUTH_MODE=clerk
CLERK_ISSUER=https://...
CLERK_JWKS_URL=https://...
```

Required by the frontend when `NEXT_PUBLIC_AUTH_MODE=clerk`:

```env
NEXT_PUBLIC_AUTH_MODE=clerk
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_...
NEXT_PUBLIC_VOXQUERY_TENANT_ID=<tenant UUID matching vox_tenant_id>
```

Optional but recommended for staging/production:

```env
CLERK_AUDIENCE=https://api.voxquery.com
```

Leave `CLERK_AUDIENCE` unset or blank for the first local smoke unless the Clerk token is
configured with a matching `aud` claim. Blank optional Clerk env values are treated as unset.

The frontend sends Clerk tokens as REST `Authorization: Bearer <jwt>` headers and as
`token=<jwt>` query params for `/ws/audio` and `/ws/pipeline`. Backend access logs redact
the `token` query param. Do not commit Clerk secrets or local `.env` files.
