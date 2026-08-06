# Versioning advisory

Updated: 2026-08-06

Status: `v2.5.0` is the published product baseline. Current unreleased source
implements HTTP contract 2, while the published 2.5.0 artifact used contract 1.
A separate service-version field still awaits an explicit platform
requirement.

## Recommendation

Do not reset the existing AI Guard product from `2.5.0` to `0.1.0` in this
repository. Published `v1.x` and `v2.x` tags, desktop updater metadata, package
manifests, extension versions, and download URLs already identify one monotonic
product line. A lower version would look like a downgrade and some clients
would never offer it as an update.

Use three independent numbers instead:

| Scope | Current decision | Rule |
|---|---|---|
| Desktop/extension/product `VERSION` | Published `2.5.0`; choose the next value only from delivered scope. | Monotonic SemVer; compatible fixes are a patch, additive capability is a minor, and a breaking public contract is a major. Never reset, move, or reuse a tag. |
| AI for Thai service deployment | `0.1.0` remains a possible first value, not an implemented source of truth. | Create a separate version only if the official platform requires it in an image tag, response, registry, or deployment manifest. |
| Public API contract | Current source `2`; published 2.5.0 artifact `1`. | Change only for an incompatible caller contract; independent of either release line. The first release containing current contract 2 is expected to require product `3.0.0`, but release preparation and version change are not authorized by source hardening work. |

The service version should become a separate source such as
`AIFORTHAI_SERVICE_VERSION` only after the platform confirms where it must
appear. Do not duplicate it across files or bump the product version for
documentation, acceptance, or adapter preparation.

## If every visible version must be `0.1.x`

That is a new product identity, not a normal version bump. It requires a new
application/package identifier, updater feed, release/package names, and
usually a new repository or explicitly named distribution channel. Existing
`v2.x` releases remain archived; their tags must not be deleted or rewritten.

The split above communicates the newer service line's prototype maturity
(`AI for Thai service 0.1.x`) without breaking installed AI Guard clients or
falsifying release history.
