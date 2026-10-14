# First-time research setup

`/onboarding` is a six-step account setup: role, field, workplace, first question,
default research depth, and review. It follows the existing copper/charcoal brand,
not the reference platform's colours. It supports custom role/field text, optional
organisation/question, back navigation, skip, keyboard focus and reduced motion.

## Persistence and access

The verified Next.js BFF at `/api/onboarding` validates bounded Zod requests and
saves `research_onboarding` in the signed-in user's Supabase Auth metadata through
`auth.updateUser`. No service-role credentials, identity parameters, schema
migration, or changes to research RLS are needed. Metadata is editable personal
preference data, **never an authorization, quota or billing source**. Existing
display-name metadata is not replaced.

Progress is saved on Continue and Back. Unsaved typing stays on the current page
after a failed save, but is not an autosaved draft. A page reload resumes the last
saved step. Skip is persisted, and completed/skipped users can edit preferences
again without being forced through setup on their next workspace visit.

Password login, immediate-session signup, OAuth callback and email confirmation
route unfinished accounts through setup. Password recovery remains separate.
The research proxy/layout also handle direct workspace visits; accounts lacking
setup metadata (including pre-existing accounts) see setup once and can skip.
Redirects use the existing destination allowlist, including saved reports.

## Actual personalization

Completing setup places the optional first question in the composer for review
and applies the selected depth. Subsequent new research pages use the depth, but
do not repeatedly insert the initial question. A user edit made while defaults
load is preserved. No research is started by setup. Existing 6/12/20 ceilings and
the two-source evergreen adjustment remain unchanged.

Role, field and workplace are stored for the account, but do not yet change model
prompts or provider routing. No academic-provider prioritization, payment,
subscription, discount, or team entitlement is claimed or activated. The final
research screenshot is inspiration only: the existing real task/evidence view
remains, with no fabricated searches, source counts or private reasoning display.

## Validation

Unit tests cover request limits, identity/CSRF checks, valid completion/skip,
failed saves, returning accounts and auth destinations. Isolated browser tests
cover six-step interaction, resumability, preserved edits, mobile layout, reduced
motion, and composer handoff. Fixture persistence uses sessionStorage **only in
the test app**; production persistence uses Supabase account metadata. No auth
bypass or fixture endpoint is shipped in the Next.js route tree.

Validate with `corepack pnpm test`, `corepack pnpm typecheck`, and
`corepack pnpm --filter @research/web build`. A real signed-in Supabase smoke test
is still needed to confirm account persistence under deployed Auth settings.
