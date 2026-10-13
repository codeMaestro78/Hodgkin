# Supabase account authentication

Email/password signup and login, Google OAuth, logout, email confirmation and password recovery are implemented. Supabase manages credentials in `auth.users`; no password table or password hashing is implemented in the application. The Next.js BFF uses `@supabase/ssr` with server-only HttpOnly cookies, refreshes sessions through `proxy.ts`, verifies identities with `getUser()`, and forwards the session bearer token to FastAPI. FastAPI independently validates that token against the configured Supabase Auth project and resolves a provisioned personal workspace. Client identity headers and user-editable metadata never select a tenant.

Implementation follows the [Supabase SSR guide](https://supabase.com/docs/guides/auth/server-side/creating-a-client), [Google OAuth guide](https://supabase.com/docs/guides/auth/social-login/auth-google), and [user-data/trigger guide](https://supabase.com/docs/guides/auth/managing-user-data).

## Configuration

Copy `apps/web/.env.local.example` and `services/research-api/.env.example` as needed. The current local environment has the supplied public Supabase URL and publishable key configured. Neither a service-role key nor a Google client secret belongs in browser code.

| Location | Variables |
| --- | --- |
| Next.js | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `NEXT_PUBLIC_APP_URL` |
| Next.js BFF | `RESEARCH_API_URL`, `INTERNAL_SERVICE_AUTH` |
| Python API | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, matching `INTERNAL_SERVICE_AUTH`, database settings |

`NEXT_PUBLIC_APP_URL` is the trusted canonical origin used for OAuth callbacks, email links and same-origin POST checks. Use `http://localhost:3000` locally and your HTTPS app URL in production. Restart processes after configuration changes. The public variables must be available at build time as well as runtime for deployments that inline public configuration.

In Supabase Authentication → URL Configuration:

- Set the Site URL to the application origin.
- Allow `http://localhost:3000/auth/callback` and `http://localhost:3000/auth/confirm` for local development, plus the equivalent production URLs. Supabase redirect matching may include query strings: if exact callback entries fail for the `next` parameter, add narrowly scoped `http://localhost:3000/auth/callback**` / `auth/confirm**` entries. Do not allow arbitrary production origins.
- Email confirmation is enabled on the configured project. Signup shows the inbox-confirmation state until confirmation succeeds.

Google is already enabled in the configured project. In Google Cloud, the Web OAuth client's authorized redirect URI must be `https://<project-ref>.supabase.co/auth/v1/callback`, **not** the application's `/auth/callback`. Configure the client ID/secret in the Supabase Google provider settings. The application starts the provider through Supabase; the latter exchanges Google's credentials and sends a PKCE authorization code to the app.

For email confirmation across browsers/devices, configure the Supabase email templates to point directly at the implemented token-hash handler:

```html
<!-- Confirm signup -->
<a href="{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email">Confirm your email</a>
<!-- Reset password -->
<a href="{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=recovery">Reset password</a>
```

The default PKCE links are also supported by `/auth/callback`, but require the originating browser's verifier cookie. Use custom SMTP for production delivery; provider rate limits remain in effect. Production CAPTCHA/bot controls and stricter password policy are Supabase settings, not claimed as configured by this change.

## Database and ownership

For `apps/web/Dockerfile`, supply build arguments `NEXT_PUBLIC_APP_URL`, `NEXT_PUBLIC_SUPABASE_URL`, and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`; provide the server-only BFF configuration at runtime. The image also copies the public assets used by the account pages. Never pass private service or Google client secrets as public build arguments.

Run migrations from `services/research-api` with `uv run alembic upgrade head`. Revisions `0003` and `0004` have been applied to the configured Supabase database.

- `public.user_profiles`: Auth user UUID, personal tenant UUID, display name and timestamps. It references both `auth.users` and the application's tenant/user relationship. There are no password or session columns.
- An `auth.users` insert trigger creates one tenant, application user and profile for email or Google accounts. Existing Auth accounts are backfilled. The immutable personal workspace ID equals the verified Auth user UUID; metadata is used only for the display name.
- Profile RLS permits authenticated users to read their own profile and update only `full_name`. Browser roles cannot directly access research tables, edit tenant IDs, delete profiles or execute the internal provisioning functions. Explicit function revocations account for Supabase's default grants.
- Existing development tenants and reports are preserved. They are not automatically reassigned to a new account. New accounts start with private history. Legacy development identity headers do not authenticate research endpoints, even in development.

Rollback does not delete Auth users or research rows. Downgrading `0003` drops the profile table and signup trigger; this is a destructive operator action, not part of the normal implementation/test workflow.

## Routes and controls

`/login`, `/signup`, `/forgot-password`, `/reset-password`; `/auth/callback` for code exchange; `/auth/confirm` for email token hashes; `/api/auth/{login,signup,google,logout,forgot,reset}` for POST actions; `/api/auth/session` for the account strip. Research pages and all research BFF endpoints require a registered session. Cookies are HttpOnly, SameSite=Lax, and Secure in production. Auth/research responses are private and uncached. POST actions require the configured same-origin header. Auth redirects accept only research destinations and the password-reset page, not arbitrary URLs. No token, password, OAuth error description or credential values are echoed into application feedback.

Logout ends the local browser session; it is not a global all-devices logout. As with Supabase generally, previously issued access tokens may remain valid until expiry. No admin credential or global-session revocation flow is added.

## Verification and remaining manual checks

Validated: production build and typecheck; 19 frontend unit tests; 27 backend unit tests plus the isolated database test; 17 browser checks. Hosted introspection confirms migration `0004`, profile RLS, the signup trigger, no direct browser research-table access, and no browser execution privilege on provisioning helpers. The running API rejects a request containing the legacy development identity with status 401.

- Frontend Auth unit tests cover credential validation, signup confirmation, Google initiation, callback/OTP errors, password recovery, logout, redirect filtering and research bearer forwarding. Supabase calls are mocked in these tests.
- Backend unit tests cover service-auth/session requirements, invalid/anonymous/unconfirmed identities, metadata/header spoof rejection and missing provisioning. Auth responses are mocked.
- `RUN_AUTH_SCHEMA_TESTS=1 uv run pytest tests/integration/test_auth_schema.py` builds a disposable **local** PostgreSQL database, exercises signup triggers and RLS with two fixture users, mimics Supabase default function grants, and rolls back/drops only that test database. It never creates hosted test accounts or touches hosted research data.
- [authentication-browser-check.js](authentication-browser-check.js) checks real anonymous route protection, CSRF rejection, real Google authorization initiation/cookie attributes, account form behavior using browser-local response fixtures, denied callbacks and mobile overflow. It does not complete Google consent or send signup/reset emails.

Remaining manual smoke test: create your own account at `/signup`, confirm the email, sign in, confirm the private history, sign out, then try “Continue with Google” and password recovery. Google consent, real email delivery, cross-browser confirmation templates and an authenticated research run require this user-owned check. The old anonymous/local-preview design-check scripts describe the pre-auth UI and are not the current account smoke test.
