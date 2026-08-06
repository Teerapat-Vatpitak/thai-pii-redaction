# Session-namespaced token identity

Date: 2026-08-06
Status: accepted

## Context

Token mode previously identified a replacement with only its localized data
type and ordinal, for example `[โทรศัพท์_1]`. That identity was unique only
inside one vault. After a session was dropped, expired, evicted, or lost on
backend restart, a replacement session could mint the same visible token for a
different original.

If a client then submitted text retained from the old session while holding the
new `session_id`, reverse mapping treated the old token as the new session's
token. The result silently restored unrelated data and produced neither a
leftover nor a foreign-replacement warning. Client retry logic cannot close
this gap because a retry is exactly how a replacement session can be created.

Generation separation alone also left a same-session preplay path. Once an
external model could see a generation tag and the next ordinal, it could emit
a syntactically valid future token. If that token was later minted for a real
value in the same session, retained model text could change from foreign to
trusted and restore data that was never present when the text was created.

The canonical mapping still belongs only to the backend vault. Solving token
identity must not add a mapping, credential, or session identifier to the HTTP
response schema.

## Decision

### 1. Token identity includes a vault-generation tag and per-token nonce

Token mode now emits:

```text
[<localized-label>_<generation-tag>_<token-nonce>_<ordinal>]
```

The generation tag is 25 lowercase letters from `a` through `f`, encoding one
uniformly generated 64-bit random value. It is:

- created independently for each vault lifecycle;
- stable for every token minted by that vault;
- not derived from the original value, source text, salt, `session_id`, or any
  credential; and
- a non-secret identity discriminator, not authentication or authorization.

The letters-only alphabet prevents the tag itself from creating the
detector-independent six-digit residual signal. The fixed shape lets the core
distinguish product tokens from arbitrary bracket text without serializing a
separate namespace field.

The token nonce is 20 lowercase letters from `a` through `z`, selected with a
cryptographic random generator for each newly minted token. It carries about
94 bits of unpredictability. It remains stable only because the vault reuses
the complete existing token for the same original; it is not derived from the
label, ordinal, original, source, salt, session ID, or generation tag.

The ordinal remains a positive ASCII decimal integer and continues to express
the first-seen order of distinct values of one data type within the vault. It
is descriptive, not sufficient identity. A newly minted token is accepted only
after its full tag/nonce/ordinal string is absent from the source and vault
reverse index. Bounded nonce collisions fail with a constant value-free error.

### 2. The vault owns the tag

`SessionVault` owns the generation tag and complete minted-token records.
Detached transaction clones,
snapshots, and rollback state preserve it so a successful multi-turn session
does not change token identity. Clearing a vault drops its tag together with
the mapping references; reusing that Python object generates a new tag before
it can mint another token.

The tag does not replace `session_id`. Clients still retain only the opaque
session reference needed to address backend state, while token text can pass
through an external model as pseudonymized content.

### 3. Stale tokens fail closed

Reverse mapping restores only exact pseudonyms owned by the active vault. A
token-shaped value from another generation remains unchanged and is counted as
`foreign_replacement`. First-party v2 clients already treat that count-only
warning as unsafe and prevent Copy, Apply, Insert, clipboard, composer, or
document writes.

The core never guesses that two tokens with the same label and ordinal mean the
same original. It also never translates an old namespace into a current one.
An exact current-format token that the active vault did not send remains
foreign even when the replacement session uses surrogate mode. The nonce makes
a future token computationally impractical to preplay from a visible namespace
and predictable ordinal.

### 4. Stateless continuity is explicit

Independent stateless token calls receive independent generation tags even
when their input and salt are identical. This deliberately removes the old
same-salt token-string reproducibility. Surrogate-mode determinism is
unchanged.

An explicit caller-held `prior_mapping` remains the stateless continuity
boundary:

- when its admissible namespaced tokens contain exactly one generation tag,
  newly minted tokens continue that tag;
- valid prior token/original pairs reuse the complete token, including nonce;
- zero or multiple tags do not select a tag for new tokens;
- admitted same-type ordinals continue from the highest prior ordinal, including
  a legacy token at this boundary; and
- legacy `[<label>_<ordinal>]` values remain readable only through this
  explicit prior-mapping path and are never minted by current code.

A token-shaped prior-mapping key is not trusted merely because its syntax is
valid. The parser requires the exact label/tag/nonce/ordinal grammar with no
embedded bracket or newline. The key must then pass the existing value-free
seed admission rules and the full structured, text-based, and
detector-independent residual policy before it can be reused or select a
namespace. This order prevents malformed or residual-bearing caller text from
controlling newly minted identity.

Continuity examines live admitted prior entries even when their originals are
absent from the next turn. When an original is detected in the current turn,
the token label must match one of that original's detected data types before it
can contribute continuity. This prevents a self-declared wrong label from
selecting the namespace while preserving the common "next turn contains only
new PII" chain. If duplicate mappings name the same original, token reuse
searches all live candidates rather than letting an earlier wrong-label entry
hide a later admissible one.

### 5. Wire contracts do not grow

HTTP v2 response schemas do not add a namespace field. The sanitized text and
its sanitized-space highlights naturally reflect the longer replacement, while
clients continue to treat replacement text as opaque. Existing strict DTOs,
count-only warnings, and Unicode code-point offset rules remain unchanged.

The worker envelope remains version 1. The separately versioned
`aiguard-aift` repository is unaffected.

## Alternatives rejected

- **Client retry or session disposal alone.** These improve lifecycle hygiene
  but cannot identify text retained from a previous vault.
- **Embedding `session_id`.** This would expose session authority wherever
  pseudonymized text is sent and couple visible data to the transport
  lifecycle.
- **Deriving the tag or nonce from input or salt.** Determinism would recreate
  cross-session identity collisions and could disclose linkability.
- **Namespace plus ordinal without a nonce.** A visible namespace and
  predictable next ordinal allow same-session future-token preplay.
- **Remembering every previously foreign token.** This adds unbounded,
  attacker-controlled state and still depends on observing every prior reply.
- **Restoring by label and ordinal.** This is the original defect and can
  insert an unrelated person's data.
- **A process-global mapping registry.** It would retain cross-session state,
  complicate restart behavior, and weaken the in-memory lifecycle boundary.

## Required evidence

The implementation must prove:

- old token text is not restored after drop, restart, idle expiry, or LRU
  eviction followed by a token- or surrogate-mode replacement session;
- each case returns zero replacements and one count-only foreign warning;
- a syntactically valid future token retained from an earlier reply remains
  foreign after the corresponding label and ordinal are later minted in the
  same session;
- one session preserves its tag across successful calls, detached transaction
  clones, snapshot/restore, and rollback;
- `clear()` invalidates the tag before vault-object reuse;
- fresh stateless token calls use different tags, while an explicit valid
  prior mapping preserves continuity;
- malformed or residual-bearing token-shaped seed keys cannot bypass residual
  scanning or select the minting namespace; wrong-label and ambiguous
  multi-namespace seeds cannot select a tag either;
- a new token retries a source/vault identity collision with a fresh nonce, and
  bounded exhaustion returns a value-free failure without publishing state;
- client validators and highlights accept the longer opaque replacement
  without learning a mapping or new credential; and
- the full Python, JavaScript, Office, Rust, packaging, privacy, and
  documentation gates required by the affected HTTP-v2 cutover pass on the
  exact candidate; performance is measured separately, and any budget
  exception requires explicit owner acceptance.

## Consequences

- Token text is longer and visually different. Tests, examples, and any caller
  that incorrectly parsed the old undocumented shape must change.
- On the exact 2026-08-06 candidate, the longer token text crossed the
  500-character outbound TB-NER chunk boundary. A three-pair controlled
  comparison measured sanitize at `28.69 ms` versus `18.37 ms` on base
  `c533ec9` (`+56.2%`), over the 20% time budget. The owner accepted this
  security trade on 2026-08-06 rather than weakening full original-text
  residual scanning. The committed performance baseline remains unchanged.
- A repeated stateless token call without `prior_mapping` no longer produces
  byte-identical token text. Callers that need continuity must pass the
  mapping they already own.
- Generation tags and token nonces provide probabilistic identity separation,
  not server authentication. Neither value is a credential. The native-broker
  work remains required for localhost process identity.
- Session expiry, authenticated disposal, and client continuity remain
  separate lifecycle concerns; namespaced tokens make their failure mode safe
  but do not complete those tracks.
- This decision does not authorize a version bump, release, deployment,
  installed-client operation, live-provider call, or real-host acceptance.
