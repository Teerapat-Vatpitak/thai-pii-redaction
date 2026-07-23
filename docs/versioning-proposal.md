# Versioning proposal

Status: product patch approved; service-version split still awaits platform
requirements.

## Recommendation

Do not reset the existing AI Guard product from `2.4.0` to `0.1.0` in this
repository. Published `v1.x` and `v2.x` tags, desktop updater metadata, package
manifests, extension versions, and download URLs already identify one monotonic
product line. A lower version would look like a downgrade and some clients
would never offer it as an update.

Use three independent numbers instead:

| Scope | Recommended next value | Rule |
|---|---:|---|
| Desktop/extension/product `VERSION` | `2.4.1` for the approved compatible manifest/release fixes; `2.5.0` only when the additive Office/storefront scope passes | Monotonic SemVer; never reset or reuse a published tag. |
| AI for Thai service deployment | `0.1.0` | New deployment line; `0.1.1`, `0.1.2` for compatible fixes, `0.2.0` for a new operation or platform contract change. |
| Public API contract | current `1` | Change only for an actual incompatible caller contract; independent of both release lines. |

The service version should become a separate source such as
`AIFORTHAI_SERVICE_VERSION` only after the platform confirms where it must
appear (image tag, job result, registry metadata, or deployment manifest). Do
not duplicate it across files before that requirement exists.

## If every visible version must be `0.1.x`

That is a new product identity, not a normal version bump. It requires a new
application/package identifier, updater feed, release/package names, and
usually a new repository or explicitly named distribution channel. Existing
`v2.x` releases remain archived; their tags must not be deleted or rewritten.

For the current competition project, the split above communicates prototype
maturity (`AI for Thai service 0.1.x`) without breaking installed AI Guard
clients or falsifying release history.
