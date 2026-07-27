# Versioning policy

Status: decided and applied (the product line continued monotonically through
`v2.5.0`); the service-version split still awaits platform requirements.

## Policy

Do not reset the existing AI Guard product line to `0.1.0` in this repository.
Published `v1.x` and `v2.x` tags, desktop updater metadata, package manifests,
extension versions, and download URLs already identify one monotonic product
line. A lower version would look like a downgrade and some clients would never
offer it as an update.

Three independent numbers are used instead:

| Scope | Rule |
|---|---|
| Desktop/extension/product `VERSION` | Monotonic SemVer; never reset, move, or reuse a tag. Additive capability is a minor release, compatible fixes are a patch, a breaking public contract is a major release. |
| AI for Thai service deployment | A separate line starting at `0.1.0`; patch for compatible fixes, minor for a new operation or platform contract change. |
| Public API contract | Currently `1`; change only for an actual incompatible caller contract, independent of both release lines. |

The service version should become a separate source such as
`AIFORTHAI_SERVICE_VERSION` only after the platform confirms where it must
appear (image tag, job result, registry metadata, or deployment manifest). Do
not duplicate it across files before that requirement exists.

## If every visible version must be `0.1.x`

That is a new product identity, not a normal version bump. It requires a new
application/package identifier, updater feed, release/package names, and
usually a new repository or explicitly named distribution channel. Existing
`v2.x` releases remain archived; their tags must not be deleted or rewritten.

The split above communicates the newer service line's prototype maturity
(`0.1.x`) without breaking installed AI Guard clients or falsifying release
history.
