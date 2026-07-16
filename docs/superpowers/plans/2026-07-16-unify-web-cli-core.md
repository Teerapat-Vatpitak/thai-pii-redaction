# Unify Web + CLI Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `app/server.py`'s private `_tokenize`/`_SESSIONS` brain with a single core facade (`pii_redactor/session_service.py`) so the web path gets the vault, leak guard, reverse mapper, and output validation the CLI already has — while keeping the v2 API contract byte-compatible (additive `warnings[]` only).

**Architecture:** New `SessionService` in core owns session lifecycle (SessionVault + accumulated EntityRegistry + per-session salt/mode, cap 200 / TTL 1800s). Token mode moves into core (`anonymizer/token_generator.py`, `anonymize(mode=...)`). The pre-send leak scan is extracted from `ai_client` into `pii_redactor/leak_guard.py` and shared. `app/server.py` endpoints become thin adapters. Spec: `docs/superpowers/specs/2026-07-16-unify-web-cli-core-design.md`.

**Tech Stack:** Python 3.13, FastAPI, pytest. No new dependencies.

## Global Constraints

- Run every Python command as: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe ...` (PowerShell, repo root `C:\Users\teera\dev\thai-pii-redaction`). Bash equivalent: `PYTHONUTF8=1 ./.venv/Scripts/python.exe ...`
- **Commit messages MUST NOT contain any `Co-Authored-By: Claude ...` trailer** (standing user rule).
- API contract v2 is frozen: every existing response field keeps its name, type, and semantics. New fields are additive only (`warnings: list[str]`).
- `tests/test_step11_api.py` and `tests/test_api_hardening.py` must pass **unmodified**. If one fails, the implementation is wrong — do not edit those files (exception: none for this plan).
- Version string stays `2.2.0` everywhere. No version bumps.
- Error messages and warnings must never contain PII values or pseudonym values (types and truncated entity_ids only).
- Work on branch `feat/unify-web-cli-core` (already exists, contains the spec commit).

---

### Task 1: `SessionVault.get_by_original`

**Files:**
- Modify: `pii_redactor/session_vault.py` (add method after `get_by_pseudonym`, ~line 99)
- Test: `tests/test_step4_vault.py`

**Interfaces:**
- Produces: `SessionVault.get_by_original(original: str, data_type: str | None = None) -> VaultRecord | None` — first record whose `.original` equals `original` (and `.data_type` matches when given). Touches the idle timer like the other getters. Used by Task 3 (token reuse across turns).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_step4_vault.py`:

```python
def test_get_by_original_returns_record():
    vault = SessionVault()
    rec = _make_record(original="สมชาย ใจดี", pseudonym="บุญชัย")
    vault.write(rec)
    found = vault.get_by_original("สมชาย ใจดี")
    assert found is rec


def test_get_by_original_filters_by_data_type():
    vault = SessionVault()
    a = _make_record(original="1234", pseudonym="[บัตรประชาชน_1]")
    a.data_type = "THAI_ID"
    b = _make_record(original="1234", pseudonym="[โทรศัพท์_1]")
    b.data_type = "PHONE"
    vault.write(a)
    vault.write(b)
    assert vault.get_by_original("1234", data_type="PHONE") is b
    assert vault.get_by_original("1234", data_type="THAI_ID") is a


def test_get_by_original_missing_returns_none():
    vault = SessionVault()
    assert vault.get_by_original("ไม่มี") is None


def test_get_by_original_respects_idle_timeout():
    vault = SessionVault(idle_timeout_s=0)
    vault._last_access = time.monotonic() - 10
    with pytest.raises(VaultTimeoutError):
        vault.get_by_original("x")
```

Note: `_make_record` builds records with the SAME pseudonym default "Alice" — pass distinct pseudonyms as above so `write()`'s collision guard does not fire.

- [ ] **Step 2: Run tests to verify they fail**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_step4_vault.py -q -k get_by_original`
Expected: 4 FAIL with `AttributeError: 'SessionVault' object has no attribute 'get_by_original'`

- [ ] **Step 3: Implement** — add to `pii_redactor/session_vault.py` right after `get_by_pseudonym`:

```python
    def get_by_original(self, original: str, data_type: str | None = None) -> VaultRecord | None:
        """Lookup by original value (optionally narrowed by data_type).

        Linear scan — vaults are per-session and small. Used by token-mode
        pseudonym reuse so the same original gets the same token across turns.

        Raises:
            VaultTimeoutError: If vault has been idle past timeout threshold
        """
        self.check_idle()
        self._touch()
        for record in self._table.values():
            if record.original == original and (
                data_type is None or record.data_type == data_type
            ):
                self._audit("read_by_original", record.entity_id)
                return record
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_step4_vault.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add pii_redactor/session_vault.py tests/test_step4_vault.py
git commit -m "feat(vault): get_by_original lookup for cross-turn token reuse"
```

---

### Task 2: Token generator in core

**Files:**
- Create: `pii_redactor/anonymizer/token_generator.py`
- Test: `tests/test_step3_pseudonymize.py` (append)

**Interfaces:**
- Produces: `generate_token(data_type: str, ordinal: int) -> str` returning e.g. `"[ชื่อ_1]"`, and `TOKEN_LABEL: dict[str, str]` (the Thai label map, moved verbatim from `app/server.py:146-152` `_TOKEN_LABEL`). Unknown data_type falls back to the data_type string itself (same as server today).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_step3_pseudonymize.py`:

```python
def test_generate_token_known_type():
    from pii_redactor.anonymizer.token_generator import generate_token
    assert generate_token("NAME", 1) == "[ชื่อ_1]"
    assert generate_token("PHONE", 3) == "[โทรศัพท์_3]"


def test_generate_token_unknown_type_falls_back_to_type_name():
    from pii_redactor.anonymizer.token_generator import generate_token
    assert generate_token("MYSTERY", 2) == "[MYSTERY_2]"


def test_token_label_map_matches_v2_contract():
    from pii_redactor.anonymizer.token_generator import TOKEN_LABEL
    assert TOKEN_LABEL["THAI_ID"] == "บัตรประชาชน"
    assert TOKEN_LABEL["BANK_ACCOUNT"] == "บัญชีธนาคาร"
    assert len(TOKEN_LABEL) == 13
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_step3_pseudonymize.py -q -k token`
Expected: FAIL with `ModuleNotFoundError: No module named 'pii_redactor.anonymizer.token_generator'`

- [ ] **Step 3: Implement** — create `pii_redactor/anonymizer/token_generator.py`:

```python
"""Bracket-token pseudonyms (e.g. [ชื่อ_1]) — the web AI-Guard default mode.

Explicit and visually robust for AI round-trips. The Thai label map is the
single source of truth (moved here from app/server.py during the core unify).
"""
from __future__ import annotations

TOKEN_LABEL: dict[str, str] = {
    "NAME": "ชื่อ", "SURNAME": "นามสกุล", "THAI_ID": "บัตรประชาชน",
    "PHONE": "โทรศัพท์", "EMAIL": "อีเมล", "ADDRESS": "ที่อยู่",
    "BANK_ACCOUNT": "บัญชีธนาคาร", "CREDIT_CARD": "บัตรเครดิต",
    "DATE_OF_BIRTH": "วันเกิด", "PASSPORT": "พาสปอร์ต",
    "STUDENT_ID": "รหัสนักศึกษา", "VEHICLE_PLATE": "ทะเบียนรถ", "IBAN": "ไอแบน",
}


def generate_token(data_type: str, ordinal: int) -> str:
    """Return the bracket token for the ordinal-th distinct value of a type."""
    label = TOKEN_LABEL.get(data_type, data_type)
    return f"[{label}_{ordinal}]"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_step3_pseudonymize.py -q -k token`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pii_redactor/anonymizer/token_generator.py tests/test_step3_pseudonymize.py
git commit -m "feat(anonymizer): bracket-token generator in core (label map moved from server)"
```

---

### Task 3: `anonymize(mode="token")`

**Files:**
- Modify: `pii_redactor/anonymizer/anonymizer.py`
- Test: `tests/test_step3_pseudonymize.py` (append)

**Interfaces:**
- Consumes: `generate_token`, `TOKEN_LABEL` (Task 2); `SessionVault.get_by_original` (Task 1).
- Produces: `anonymize(text, entity_registry, vault, *, salt, mode="surrogate") -> PseudonymizedDocument`. `mode="surrogate"` is the exact current behavior (default — CLI callers unchanged). `mode="token"` assigns `[label_N]` tokens: same `(data_type, original)` reuses its token (via `vault.get_by_original`), a new original gets ordinal = number of distinct originals of that data_type already in the vault + 1 (continues across turns). If a token string somehow already exists in the source text, the ordinal is bumped until free.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_step3_pseudonymize.py`:

```python
def test_anonymize_token_mode_brackets_and_counters():
    text = "email a@b.co and c@d.co and a@b.co"
    e1 = _make_entity("EMAIL", text, 6, 12)     # a@b.co
    e2 = _make_entity("EMAIL", text, 17, 23)    # c@d.co
    e3 = _make_entity("EMAIL", text, 28, 34)    # a@b.co again
    registry = EntityRegistry(entities=[e1, e2, e3], fp_count=3, tb_count=0)
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT, mode="token")
    assert "[อีเมล_1]" in result.text and "[อีเมล_2]" in result.text
    assert "a@b.co" not in result.text and "c@d.co" not in result.text
    # same original -> same token
    p1 = vault.get_by_entity_id(e1.entity_id).pseudonym
    p3 = vault.get_by_entity_id(e3.entity_id).pseudonym
    assert p1 == p3
    # distinct originals -> distinct ordinals
    p2 = vault.get_by_entity_id(e2.entity_id).pseudonym
    assert p2 != p1


def test_anonymize_token_mode_ordinal_continues_across_calls():
    """Second call on the SAME vault (multi-turn) must not reuse ordinal 1."""
    vault = SessionVault()
    t1 = "email a@b.co"
    e1 = _make_entity("EMAIL", t1, 6, 12)
    anonymize(t1, EntityRegistry(entities=[e1], fp_count=1, tb_count=0),
              vault, salt=SALT, mode="token")
    t2 = "email x@y.co"
    e2 = _make_entity("EMAIL", t2, 6, 12)
    r2 = anonymize(t2, EntityRegistry(entities=[e2], fp_count=1, tb_count=0),
                   vault, salt=SALT, mode="token")
    assert "[อีเมล_2]" in r2.text


def test_anonymize_token_mode_same_original_across_calls_reuses_token():
    vault = SessionVault()
    t1 = "email a@b.co"
    e1 = _make_entity("EMAIL", t1, 6, 12)
    r1 = anonymize(t1, EntityRegistry(entities=[e1], fp_count=1, tb_count=0),
                   vault, salt=SALT, mode="token")
    t2 = "again a@b.co"
    e2 = _make_entity("EMAIL", t2, 6, 12)
    r2 = anonymize(t2, EntityRegistry(entities=[e2], fp_count=1, tb_count=0),
                   vault, salt=SALT, mode="token")
    assert "[อีเมล_1]" in r1.text and "[อีเมล_1]" in r2.text


def test_anonymize_default_mode_is_surrogate():
    text = "email a@b.co now"
    e1 = _make_entity("EMAIL", text, 6, 12)
    registry = EntityRegistry(entities=[e1], fp_count=1, tb_count=0)
    vault = SessionVault()
    result = anonymize(text, registry, vault, salt=SALT)
    assert "[" not in result.text  # no bracket tokens in surrogate mode
    assert "a@b.co" not in result.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_step3_pseudonymize.py -q -k "token_mode or default_mode"`
Expected: FAIL with `TypeError: anonymize() got an unexpected keyword argument 'mode'` (3 tests) / PASS for default-mode test is acceptable only after mode param exists — expect 4 FAIL initially.

- [ ] **Step 3: Implement** — in `pii_redactor/anonymizer/anonymizer.py`:

3a. Add import at top with the other generator imports:

```python
from pii_redactor.anonymizer.token_generator import generate_token
```

3b. Add helper after `_generate_unique_pseudonym`:

```python
def _next_token(entity: Entity, text: str, vault: SessionVault) -> str:
    """Token-mode pseudonym: reuse the token of the same (data_type, original);
    otherwise take the next ordinal for that data_type (continues across turns
    because the count comes from the vault, not from this call)."""
    existing = vault.get_by_original(entity.original_text, data_type=entity.data_type)
    if existing is not None:
        return existing.pseudonym
    distinct = {
        r.original for r in vault._table.values() if r.data_type == entity.data_type
    }
    ordinal = len(distinct) + 1
    token = generate_token(entity.data_type, ordinal)
    # a bracket token colliding with source text is near-impossible; bump anyway
    while token in text or token in vault._reverse:
        ordinal += 1
        token = generate_token(entity.data_type, ordinal)
    return token
```

3c. Change the `anonymize` signature and generation call:

```python
def anonymize(
    text: str,
    entity_registry: EntityRegistry,
    vault: SessionVault,
    *,
    salt: str,
    mode: str = "surrogate",
) -> PseudonymizedDocument:
```

and inside the entity loop replace the single `_generate_unique_pseudonym` call:

```python
        else:
            if mode == "token":
                pseudonym = _next_token(entity, text, vault)
            else:
                pseudonym = _generate_unique_pseudonym(
                    entity, text, salt, vault, all_originals
                )
```

3d. Update the module docstring line 2 ("Algorithm:") to mention the two modes:

```python
"""Pseudonymization orchestrator.

Two modes: mode="surrogate" (default) draws realistic fake values from
fp_generator/tb_generator with collision-safe re-rolls; mode="token" emits
bracket tokens like [ชื่อ_1] via token_generator (web AI-Guard default).
...
```

(keep the rest of the existing docstring numbered algorithm as-is)

- [ ] **Step 4: Run tests to verify they pass**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_step3_pseudonymize.py tests\test_step9_pipeline.py -q`
Expected: all PASS (pipeline tests prove surrogate default unchanged)

- [ ] **Step 5: Commit**

```bash
git add pii_redactor/anonymizer/anonymizer.py tests/test_step3_pseudonymize.py
git commit -m "feat(anonymizer): token mode with vault-backed ordinals (multi-turn safe)"
```

---

### Task 4: Extract shared leak guard

**Files:**
- Create: `pii_redactor/leak_guard.py`
- Modify: `pii_redactor/ai_client.py`
- Test: `tests/test_step5_ai_client.py` (must keep passing unmodified) + new `tests/test_leak_guard.py`

**Interfaces:**
- Produces: `scan_outbound_leaks(text: str, vault: SessionVault) -> list[Entity]` — pure function (never raises), returning entities considered REAL leaks. It is a verbatim extraction of the leak-check part of `ai_client._validate_pre_send` (`pii_redactor/ai_client.py:120-206`, the code between building `known_pseudonyms` and the `if real_leaks:` raise) plus the two helpers `_pseudonym_ranges` and `_cue_leak_in_window` which MOVE to the new module.
- `ai_client._validate_pre_send` keeps its exact behavior (raise `PreSendValidationError` on ANY leak) by calling the new function.

- [ ] **Step 1: Write the failing test** — create `tests/test_leak_guard.py`:

```python
"""Shared outbound leak scan (extracted from ai_client for web/CLI reuse)."""
import time
import uuid

from pii_redactor.leak_guard import scan_outbound_leaks
from pii_redactor.models import VaultRecord
from pii_redactor.session_vault import SessionVault


def _vault(pairs):
    v = SessionVault()
    for data_type, original, pseudonym in pairs:
        v.write(VaultRecord(
            entity_id=str(uuid.uuid4()), original=original, pseudonym=pseudonym,
            type="FP" if data_type not in ("NAME", "ADDRESS") else "TB",
            data_type=data_type, span=(0, 1), timestamp=time.monotonic(),
        ))
    return v


def test_scan_clean_pseudonymized_text_returns_empty():
    vault = _vault([("NAME", "สมชาย ใจดี", "บุญชัย"),
                    ("PHONE", "081-234-5678", "098-625-9566")])
    text = "ผมชื่อ บุญชัย เบอร์ 098-625-9566 ขอลางาน 3 วันครับ"
    assert scan_outbound_leaks(text, vault) == []


def test_scan_flags_real_thai_id():
    vault = _vault([("NAME", "สมชาย ใจดี", "บุญชัย")])
    text = "ผมชื่อ บุญชัย เลขบัตรประชาชน 1101700230708"
    leaks = scan_outbound_leaks(text, vault)
    assert any(e.data_type == "THAI_ID" for e in leaks)


def test_scan_flags_cue_split_name():
    vault = _vault([("NAME", "สมชาย ใจดี", "บุญชัย")])
    text = "เรียน นาย บุญชัย วิชัย ทองแท้ ครับ"
    leaks = scan_outbound_leaks(text, vault)
    assert any(e.data_type == "NAME" for e in leaks)


def test_scan_never_raises_on_empty_vault():
    assert isinstance(scan_outbound_leaks("ข้อความธรรมดา", SessionVault()), list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_leak_guard.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pii_redactor.leak_guard'`

- [ ] **Step 3: Implement** — create `pii_redactor/leak_guard.py` by MOVING code from `ai_client.py`. The module must contain (moved verbatim, only re-homed):

```python
"""Outbound PII leak scan shared by the CLI pre-send guard and the web path.

A "leak" is a detector hit in already-pseudonymized text that pseudonym
occurrences cannot account for. Fuzzy NER spans around embedded pseudonyms
are excused via position-based overlap + per-segment remainder scans + a
cue-preserving name_context re-check (see PR #33/#34 history).
"""
from __future__ import annotations

from pii_redactor.detectors.fp_detector import detect_fp
from pii_redactor.detectors.name_context import detect_name_context
from pii_redactor.detectors.tb_detector import detect_tb
from pii_redactor.models import Entity
from pii_redactor.session_vault import SessionVault
```

then move `_pseudonym_ranges` (ai_client.py:99-117) and `_cue_leak_in_window` (ai_client.py, the function added in PR #34 review fixes) UNCHANGED, and add:

```python
def scan_outbound_leaks(text: str, vault: SessionVault) -> list[Entity]:
    """Return real leaks in pseudonymized text (empty list = safe to send)."""
```

whose body is the leak-check block currently inside `_validate_pre_send` (from `known_pseudonyms = set(vault._reverse.keys())` through building `real_leaks`), ending with `return real_leaks` instead of raising.

In `ai_client.py`: delete the moved helpers, import `from pii_redactor.leak_guard import scan_outbound_leaks`, and replace check 1 of `_validate_pre_send` with:

```python
    # 1. PII leak check (shared scan; see pii_redactor/leak_guard.py)
    real_leaks = scan_outbound_leaks(text, vault)
    if real_leaks:
        raise PreSendValidationError(
            f"PII detected in text before sending to AI: "
            f"{[e.data_type for e in real_leaks]}"
        )
```

Keep checks 2-4 of `_validate_pre_send` untouched. Remove now-unused imports from `ai_client.py` (`detect_fp`, `detect_tb`, `detect_name_context`) ONLY if nothing else in the file uses them — check with grep first (`_validate_response` and others may still use them; if unused, remove).

- [ ] **Step 4: Run tests to verify everything passes**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_leak_guard.py tests\test_step5_ai_client.py tests\test_step9_pipeline.py -q`
Expected: all PASS — `test_step5_ai_client.py` unmodified proves CLI behavior identical

- [ ] **Step 5: Commit**

```bash
git add pii_redactor/leak_guard.py pii_redactor/ai_client.py tests/test_leak_guard.py
git commit -m "refactor(guard): extract scan_outbound_leaks to pii_redactor/leak_guard.py"
```

---

### Task 5: `SessionService` — session lifecycle

**Files:**
- Create: `pii_redactor/session_service.py`
- Test: Create `tests/test_session_service.py`

**Interfaces:**
- Consumes: `SessionVault` (with `get_by_original` from Task 1).
- Produces (used by Tasks 6-8):

```python
class SessionExpiredError(Exception): ...
class ModeMismatchError(Exception): ...

class SessionService:
    def __init__(self, *, cap: int = 200, ttl_s: int = 1800,
                 now_fn: Callable[[], float] = time.monotonic): ...
    def _get_or_create(self, session_id: str | None, mode: str | None) -> tuple[str, "_Session"]
    def drop(self, session_id: str) -> bool
    @property
    def session_count(self) -> int
```

`_Session` dataclass fields: `vault: SessionVault`, `entities: list[Entity]` (accumulated), `mode: str`, `salt: str`, `created: float`, `last_access: float`.
Rules: unknown/expired id → `SessionExpiredError`; explicit `mode` conflicting with an existing session's mode → `ModeMismatchError`; `mode=None` inherits (new sessions default `"token"`); TTL checked against `now_fn`, `last_access` refreshed on every successful get; cap eviction drops the oldest-`created` session via the same path as `drop()` (vault null-byte `clear()`).

- [ ] **Step 1: Write the failing tests** — create `tests/test_session_service.py`:

```python
"""SessionService — the single core brain behind /api/sanitize and /api/reidentify."""
import pytest

from pii_redactor.session_service import (
    ModeMismatchError,
    SessionExpiredError,
    SessionService,
)


def _svc(**kw):
    clock = {"t": 1000.0}
    svc = SessionService(now_fn=lambda: clock["t"], **kw)
    return svc, clock


def test_create_session_defaults_to_token_mode():
    svc, _ = _svc()
    sid, session = svc._get_or_create(None, None)
    assert session.mode == "token"
    assert isinstance(sid, str) and len(sid) > 10


def test_reuse_session_inherits_mode():
    svc, _ = _svc()
    sid, _ = svc._get_or_create(None, "surrogate")
    sid2, session = svc._get_or_create(sid, None)
    assert sid2 == sid and session.mode == "surrogate"


def test_mode_conflict_raises():
    svc, _ = _svc()
    sid, _ = svc._get_or_create(None, "token")
    with pytest.raises(ModeMismatchError):
        svc._get_or_create(sid, "surrogate")


def test_unknown_session_raises_expired():
    svc, _ = _svc()
    with pytest.raises(SessionExpiredError):
        svc._get_or_create("does-not-exist", None)


def test_ttl_expiry_and_reset_on_access():
    svc, clock = _svc(ttl_s=100)
    sid, _ = svc._get_or_create(None, None)
    clock["t"] += 90
    svc._get_or_create(sid, None)          # access resets the idle timer
    clock["t"] += 90
    svc._get_or_create(sid, None)          # still alive
    clock["t"] += 101
    with pytest.raises(SessionExpiredError):
        svc._get_or_create(sid, None)


def test_cap_evicts_oldest_and_clears_vault():
    svc, clock = _svc(cap=2)
    sid1, s1 = svc._get_or_create(None, None)
    clock["t"] += 1
    sid2, _ = svc._get_or_create(None, None)
    clock["t"] += 1
    from pii_redactor.models import VaultRecord
    import time as _time
    s1.vault.write(VaultRecord(entity_id="e1", original="ลับมาก",
                               pseudonym="[ชื่อ_1]", type="TB", data_type="NAME",
                               span=(0, 5), timestamp=_time.monotonic()))
    svc._get_or_create(None, None)         # third session evicts sid1
    assert svc.session_count == 2
    with pytest.raises(SessionExpiredError):
        svc._get_or_create(sid1, None)
    # evicted vault was null-byte-cleared and emptied
    assert len(s1.vault._table) == 0


def test_drop_clears_and_reports():
    svc, _ = _svc()
    sid, session = svc._get_or_create(None, None)
    assert svc.drop(sid) is True
    assert svc.drop(sid) is False
    assert len(session.vault._table) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_session_service.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pii_redactor.session_service'`

- [ ] **Step 3: Implement** — create `pii_redactor/session_service.py`:

```python
"""Session facade unifying the web path onto the core pipeline components.

One brain: SessionVault + accumulated EntityRegistry + per-session salt/mode,
with the same cap/TTL policy the old app/server.py _SESSIONS dict had.
Sanitize/restore logic arrives in later tasks; this module owns lifecycle.

SECURITY: sessions live in memory only; dropping/evicting a session always
null-byte-clears its vault first.
"""
from __future__ import annotations

import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from pii_redactor.models import Entity
from pii_redactor.session_vault import SessionVault


class SessionExpiredError(Exception):
    """Unknown or idle-expired session."""


class ModeMismatchError(Exception):
    """Requested mode conflicts with the session's locked mode."""


@dataclass
class _Session:
    vault: SessionVault
    mode: str
    salt: str
    created: float
    last_access: float
    entities: list[Entity] = field(default_factory=list)


class SessionService:
    def __init__(
        self,
        *,
        cap: int = 200,
        ttl_s: int = 1800,
        now_fn: Callable[[], float] = time.monotonic,
    ):
        self._sessions: dict[str, _Session] = {}
        self._cap = cap
        self._ttl_s = ttl_s
        self._now = now_fn

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    def _get_or_create(
        self, session_id: str | None, mode: str | None
    ) -> tuple[str, _Session]:
        if session_id is not None:
            session = self._sessions.get(session_id)
            if session is None or self._now() - session.last_access > self._ttl_s:
                if session is not None:
                    self.drop(session_id)
                raise SessionExpiredError("Session not found or expired")
            if mode is not None and mode != session.mode:
                raise ModeMismatchError(
                    f"session mode is '{session.mode}', got '{mode}'"
                )
            session.last_access = self._now()
            return session_id, session

        if len(self._sessions) >= self._cap:
            oldest = min(self._sessions, key=lambda k: self._sessions[k].created)
            self.drop(oldest)
        sid = str(uuid.uuid4())
        now = self._now()
        # vault idle timeout mirrors the service TTL; the service check fires
        # first in practice because both reset on access
        session = _Session(
            vault=SessionVault(idle_timeout_s=self._ttl_s),
            mode=mode or "token",
            salt=secrets.token_hex(16),
            created=now,
            last_access=now,
        )
        self._sessions[sid] = session
        return sid, session

    def drop(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session.vault.clear()
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_session_service.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add pii_redactor/session_service.py tests/test_session_service.py
git commit -m "feat(core): SessionService lifecycle (cap/TTL/mode-lock, null-byte drop)"
```

---

### Task 6: `SessionService.sanitize` with hybrid guard

**Files:**
- Modify: `pii_redactor/session_service.py`
- Test: `tests/test_session_service.py` (append)

**Interfaces:**
- Consumes: `detect_all` (`pii_redactor/detectors/aggregate.py`), `anonymize(mode=...)` (Task 3), `scan_outbound_leaks` (Task 4), `scan_section26` (`pii_redactor/report.py`).
- Produces:

```python
class OutboundLeakError(Exception):
    def __init__(self, leak_types: list[str]): ...   # .leak_types attr, message has NO values

@dataclass
class SanitizeOutcome:
    session_id: str
    original_text: str
    sanitized_text: str
    entities: list[dict]          # {"start","end","data_type","redact_type","token"} — v2 shape
    entity_type_counts: dict[str, int]
    section26: list[dict]
    warnings: list[str]

SessionService.sanitize(self, text: str, *, mode: str | None = None,
                        session_id: str | None = None) -> SanitizeOutcome
```

Raises `OutboundLeakError` when the post-anonymize scan finds an FP-type leak OR `anonymize` itself raises (`PIILeakError` from its post-replace check, `ValueError` from exhausted pseudonym generation) — mask failed, text must not be returned. TB-type leaks become `warnings` entries `"possible_tb_leak:<data_type>"`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_session_service.py`:

```python
from pii_redactor.session_service import OutboundLeakError, SanitizeOutcome


def test_sanitize_token_mode_v2_shape():
    svc, _ = _svc()
    out = svc.sanitize("ติดต่อ 081-234-5678 หรือ somchai@example.com")
    assert isinstance(out, SanitizeOutcome)
    assert "081-234-5678" not in out.sanitized_text
    assert "somchai@example.com" not in out.sanitized_text
    assert "[โทรศัพท์_1]" in out.sanitized_text
    assert "[อีเมล_1]" in out.sanitized_text
    for e in out.entities:
        assert set(e) == {"start", "end", "data_type", "redact_type", "token"}
    assert out.entity_type_counts["PHONE"] == 1
    assert out.warnings == []


def test_sanitize_surrogate_mode_no_brackets():
    svc, _ = _svc()
    out = svc.sanitize("ติดต่อ 081-234-5678", mode="surrogate")
    assert "081-234-5678" not in out.sanitized_text
    assert "[" not in out.sanitized_text


def test_sanitize_multi_turn_same_token():
    svc, _ = _svc()
    o1 = svc.sanitize("เบอร์ผม 081-234-5678")
    o2 = svc.sanitize("ย้ำ เบอร์ 081-234-5678 กับอีเมล a@b.co",
                      session_id=o1.session_id)
    assert o2.session_id == o1.session_id
    tok1 = next(e["token"] for e in o1.entities if e["data_type"] == "PHONE")
    tok2 = next(e["token"] for e in o2.entities if e["data_type"] == "PHONE")
    assert tok1 == tok2


def test_sanitize_registry_accumulates_across_turns():
    svc, _ = _svc()
    o1 = svc.sanitize("เบอร์ 081-234-5678")
    svc.sanitize("อีเมล a@b.co", session_id=o1.session_id)
    _, session = svc._get_or_create(o1.session_id, None)
    types = {e.data_type for e in session.entities}
    assert {"PHONE", "EMAIL"} <= types


def test_sanitize_raises_outbound_leak_when_fp_survives(monkeypatch):
    """If a checksum-valid FP value somehow survives anonymization, refuse."""
    import pii_redactor.session_service as svc_mod
    svc, _ = _svc()

    def fake_scan(text, vault):
        from pii_redactor.models import Entity
        return [Entity(entity_id="x", redact_type="FP", data_type="THAI_ID",
                       span=(0, 13), score=1.0, original_text="1101700230708")]

    monkeypatch.setattr(svc_mod, "scan_outbound_leaks", fake_scan)
    with pytest.raises(OutboundLeakError) as exc:
        svc.sanitize("ข้อความอะไรก็ได้ 081-234-5678")
    assert "THAI_ID" in exc.value.leak_types
    assert "1101700230708" not in str(exc.value)  # no PII in the error


def test_sanitize_tb_leak_becomes_warning(monkeypatch):
    import pii_redactor.session_service as svc_mod
    svc, _ = _svc()

    def fake_scan(text, vault):
        from pii_redactor.models import Entity
        return [Entity(entity_id="x", redact_type="TB", data_type="NAME",
                       span=(0, 5), score=0.85, original_text="สมชาย")]

    monkeypatch.setattr(svc_mod, "scan_outbound_leaks", fake_scan)
    out = svc.sanitize("ข้อความ 081-234-5678")
    assert out.warnings == ["possible_tb_leak:NAME"]
    assert "สมชาย" not in " ".join(out.warnings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_session_service.py -q`
Expected: new tests FAIL with `ImportError`/`AttributeError` (no `sanitize`, no `OutboundLeakError`)

- [ ] **Step 3: Implement** — add to `pii_redactor/session_service.py`:

Imports to add:

```python
from pii_redactor.anonymizer.anonymizer import PIILeakError, anonymize
from pii_redactor.detectors.aggregate import detect_all
from pii_redactor.leak_guard import scan_outbound_leaks
from pii_redactor.models import EntityRegistry
from pii_redactor.report import scan_section26
```

New exception + dataclass:

```python
class OutboundLeakError(Exception):
    """Anonymization could not guarantee a leak-free output. NO PII in message."""

    def __init__(self, leak_types: list[str]):
        self.leak_types = leak_types
        super().__init__(f"outbound leak risk: {leak_types}")


@dataclass
class SanitizeOutcome:
    session_id: str
    original_text: str
    sanitized_text: str
    entities: list[dict]
    entity_type_counts: dict[str, int]
    section26: list[dict]
    warnings: list[str]
```

Method on `SessionService`:

```python
    def sanitize(
        self,
        text: str,
        *,
        mode: str | None = None,
        session_id: str | None = None,
    ) -> SanitizeOutcome:
        sid, session = self._get_or_create(session_id, mode)

        turn_entities = detect_all(text)
        registry = EntityRegistry(
            entities=turn_entities,
            fp_count=sum(1 for e in turn_entities if e.redact_type == "FP"),
            tb_count=sum(1 for e in turn_entities if e.redact_type == "TB"),
        )
        try:
            pseudo = anonymize(
                text, registry, session.vault,
                salt=session.salt, mode=session.mode,
            )
        except (PIILeakError, ValueError) as e:
            # mask failed — never return the text
            raise OutboundLeakError([type(e).__name__]) from e

        warnings: list[str] = []
        leaks = scan_outbound_leaks(pseudo.text, session.vault)
        fp_leaks = [e for e in leaks if e.redact_type == "FP"]
        if fp_leaks:
            raise OutboundLeakError(sorted({e.data_type for e in fp_leaks}))
        # only register this turn once the guard has cleared the output
        session.entities.extend(turn_entities)
        warnings.extend(
            f"possible_tb_leak:{e.data_type}"
            for e in leaks if e.redact_type != "FP"
        )

        out_entities = []
        for e in turn_entities:
            record = session.vault.get_by_entity_id(e.entity_id)
            out_entities.append({
                "start": e.span[0], "end": e.span[1],
                "data_type": e.data_type, "redact_type": e.redact_type,
                "token": record.pseudonym if record else "",
            })
        type_counts: dict[str, int] = {}
        for e in out_entities:
            type_counts[e["data_type"]] = type_counts.get(e["data_type"], 0) + 1

        return SanitizeOutcome(
            session_id=sid,
            original_text=text,
            sanitized_text=pseudo.text,
            entities=out_entities,
            entity_type_counts=type_counts,
            section26=scan_section26(text),
            warnings=warnings,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_session_service.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add pii_redactor/session_service.py tests/test_session_service.py
git commit -m "feat(core): SessionService.sanitize — detect_all + anonymize + hybrid leak guard"
```

---

### Task 7: `SessionService.restore` with validator warnings

**Files:**
- Modify: `pii_redactor/session_service.py`, `pii_redactor/reverse_mapper.py` (one additive line)
- Test: `tests/test_session_service.py` (append) + `tests/test_step6_reverse.py` (one additive test)

**Interfaces:**
- Consumes: `reverse_map` (`pii_redactor/reverse_mapper.py`), `validate_output` + `PIILeakError` (`pii_redactor/output_validator.py`), `AIResponse` model.
- Produces:

```python
@dataclass
class RestoreOutcome:
    restored_text: str
    replaced: list[dict]        # {"token": pseudonym, "original": original} — v2 shape
    replaced_count: int
    leftover_tokens: list[str]
    warnings: list[str]

SessionService.restore(self, session_id: str, text: str) -> RestoreOutcome
```

Also: `reverse_mapper._post_reverse_validate` adds `audit_summary["replaced_pseudonyms"] = list(replaced)` (additive dict key) so the service can build the v2 `replaced` pairs without re-implementing longest-first logic.
Restore NEVER raises on validation findings — everything becomes `warnings` (inbound direction). Only `SessionExpiredError` (bad session) and `ValueError` (empty text, translated by the adapter later) escape.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_session_service.py`:

```python
from pii_redactor.session_service import RestoreOutcome


def test_restore_round_trip_token_mode():
    svc, _ = _svc()
    out = svc.sanitize("เบอร์ 081-234-5678 อีเมล a@b.co")
    ai_reply = f"สรุปให้: ติดต่อที่ {out.sanitized_text} นะครับ"
    r = svc.restore(out.session_id, ai_reply)
    assert isinstance(r, RestoreOutcome)
    assert "081-234-5678" in r.restored_text
    assert "a@b.co" in r.restored_text
    assert r.replaced_count >= 2
    tokens = {p["token"] for p in r.replaced}
    assert any(t.startswith("[โทรศัพท์_") for t in tokens)
    assert r.leftover_tokens == []


def test_restore_partial_reply_restores_what_it_can():
    """AI reply that mangles one token: the intact token still restores and
    the incomplete-reverse condition surfaces as a warning, never an error."""
    svc, _ = _svc()
    out = svc.sanitize("เบอร์ 081-234-5678 อีเมล a@b.co")
    phone_token = next(e["token"] for e in out.entities if e["data_type"] == "PHONE")
    email_token = next(e["token"] for e in out.entities if e["data_type"] == "EMAIL")
    reply = f"{phone_token} และ {email_token[:-1]}}}"  # email token mangled
    r = svc.restore(out.session_id, reply)
    assert phone_token not in r.restored_text
    assert "081-234-5678" in r.restored_text
    assert "a@b.co" not in r.restored_text
    assert any(w.startswith("incomplete_reverse") for w in r.warnings)


def test_restore_unknown_session_raises():
    svc, _ = _svc()
    with pytest.raises(SessionExpiredError):
        svc.restore("nope", "text")


def test_restore_warns_on_ai_generated_pii():
    """AI reply contains a checksum-valid Thai ID that is NOT in the vault —
    inbound data, so warn (never block)."""
    svc, _ = _svc()
    out = svc.sanitize("เบอร์ 081-234-5678")
    reply = f"{out.sanitized_text} และเลขบัตร 1101700230708"
    r = svc.restore(out.session_id, reply)
    assert "081-234-5678" in r.restored_text
    assert any(w.startswith("ai_generated_pii") for w in r.warnings)


def test_restore_multi_turn_uses_accumulated_registry():
    svc, _ = _svc()
    o1 = svc.sanitize("เบอร์ 081-234-5678")
    o2 = svc.sanitize("อีเมล a@b.co", session_id=o1.session_id)
    combined = o1.sanitized_text + " " + o2.sanitized_text
    r = svc.restore(o1.session_id, combined)
    assert "081-234-5678" in r.restored_text and "a@b.co" in r.restored_text
```

and append to `tests/test_step6_reverse.py`:

```python
def test_audit_summary_lists_replaced_pseudonyms():
    """Additive key used by SessionService to build the v2 replaced[] pairs."""
    import time as _t
    import uuid as _u
    from pii_redactor.models import AIResponse, EntityRegistry, VaultRecord
    from pii_redactor.reverse_mapper import reverse_map
    from pii_redactor.session_vault import SessionVault

    vault = SessionVault()
    vault.write(VaultRecord(entity_id=str(_u.uuid4()), original="a@b.co",
                            pseudonym="[อีเมล_1]", type="FP", data_type="EMAIL",
                            span=(0, 6), timestamp=_t.monotonic()))
    resp = AIResponse(text="ส่งไปที่ [อีเมล_1]", request_id="r", latency=0.0)
    result = reverse_map(resp, EntityRegistry(entities=[], fp_count=0, tb_count=0), vault)
    assert result.audit_summary["replaced_pseudonyms"] == ["[อีเมล_1]"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_session_service.py tests\test_step6_reverse.py -q`
Expected: new tests FAIL (`no attribute 'restore'`, `KeyError: 'replaced_pseudonyms'`)

- [ ] **Step 3: Implement**

3a. In `pii_redactor/reverse_mapper.py` `_post_reverse_validate`, add one line to `audit_summary` (after `"restored_pii_types"`):

```python
        "replaced_pseudonyms": list(replaced),
```

3b. In `pii_redactor/session_service.py` add imports:

```python
from pii_redactor.models import AIResponse
from pii_redactor.output_validator import PIILeakError as OutputPIILeakError
from pii_redactor.output_validator import validate_output
from pii_redactor.reverse_mapper import reverse_map
```

(note: `anonymizer` and `output_validator` each define their own `PIILeakError` — alias the second to avoid the name clash)

3c. Add `RestoreOutcome` dataclass (fields as in Interfaces) and the method:

```python
    def restore(self, session_id: str, text: str) -> RestoreOutcome:
        sid, session = self._get_or_create(session_id, None)
        registry = EntityRegistry(
            entities=session.entities,
            fp_count=sum(1 for e in session.entities if e.redact_type == "FP"),
            tb_count=sum(1 for e in session.entities if e.redact_type == "TB"),
        )
        response = AIResponse(text=text, request_id=sid, latency=0.0)
        reverse_result = reverse_map(response, registry, session.vault)

        warnings = list(reverse_result.flags)
        try:
            validation = validate_output(reverse_result, registry, session.vault)
            warnings.extend(f for f in validation.flags if f not in warnings)
        except OutputPIILeakError:
            # inbound direction: the AI fabricated PII-looking data — warn only
            warnings.append("ai_generated_pii")

        replaced_pseudonyms = reverse_result.audit_summary.get(
            "replaced_pseudonyms", []
        )
        replaced = []
        for pseudonym in replaced_pseudonyms:
            record = session.vault.get_by_pseudonym(pseudonym)
            if record is not None:
                replaced.append({"token": pseudonym, "original": record.original})

        leftover = [
            p for p in session.vault._reverse if p in reverse_result.text
        ]
        return RestoreOutcome(
            restored_text=reverse_result.text,
            replaced=replaced,
            replaced_count=len(replaced),
            leftover_tokens=leftover,
            warnings=warnings,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_session_service.py tests\test_step6_reverse.py tests\test_step7_validation.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add pii_redactor/session_service.py pii_redactor/reverse_mapper.py tests/test_session_service.py tests/test_step6_reverse.py
git commit -m "feat(core): SessionService.restore — reverse_map + validator warnings (inbound never blocks)"
```

---

### Task 8: Rewire `app/server.py` to `SessionService`, delete the second brain

**Files:**
- Modify: `app/server.py`
- Test: `tests/test_step11_api.py`, `tests/test_api_hardening.py` (RUN ONLY — no edits), `tests/test_e2e_examples.py` (run only)

**Interfaces:**
- Consumes: everything from Tasks 5-7 (`SessionService`, `SanitizeOutcome`, `RestoreOutcome`, `SessionExpiredError`, `ModeMismatchError`, `OutboundLeakError`).
- Produces: same v2 endpoints + additive `warnings[]`; `SanitizeRequest` gains `session_id: str | None = None` and `mode` default changes to `None` (adapter resolves `None` → session's mode → `"token"` — request-visible behavior identical).

- [ ] **Step 1: Rewire — edit `app/server.py`:**

1a. Replace the session-store block (`_SESSIONS`/`_SESSION_CAP`/`_SESSION_TTL_S`/`_store_session`/`_get_active_session`/`_drop_session`, lines ~105-142) with:

```python
_SESSION_CAP = 200
_SESSION_TTL_S = 1800


def _now() -> float:
    return time.monotonic()


# The single core brain. now_fn is late-bound through the module global so
# tests that monkeypatch app.server._now keep working.
from pii_redactor.session_service import (  # noqa: E402
    ModeMismatchError,
    OutboundLeakError,
    SessionExpiredError,
    SessionService,
)

SERVICE = SessionService(cap=_SESSION_CAP, ttl_s=_SESSION_TTL_S, now_fn=lambda: _now())
```

1b. Delete `_TOKEN_LABEL`, `_make_surrogate`, `_tokenize` entirely (lines ~145-228). Delete the now-unused imports `generate_fp`, `generate_tb`, `detect_all`, `scan_fn`, `uuid`? — check each with grep before removing (`uuid` is still used by `/api/analyze` and `/api/redact-pdf`; `detect_fp`/`detect_tb` still used by `/api/analyze` and `/api/redact-pdf`; `scan_fn` becomes unused — remove; `detect_all` becomes unused — remove; `generate_fp`/`generate_tb` unused — remove; `scan_section26` still used by `/api/redact-pdf` — keep).

1c. Update the request model:

```python
class SanitizeRequest(BaseModel):
    text: str
    mode: str | None = None      # "token" (default) | "surrogate"; None inherits session mode
    session_id: str | None = None  # reuse an existing session for multi-turn consistency
```

1d. Replace the `/api/sanitize` endpoint body:

```python
@app.post("/api/sanitize")
def sanitize(request: SanitizeRequest):
    start = time.time()
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")
    mode = request.mode if request.mode in ("token", "surrogate") else None
    clean_text = clean(request.text).text
    try:
        out = SERVICE.sanitize(clean_text, mode=mode, session_id=request.session_id)
    except SessionExpiredError:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    except ModeMismatchError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OutboundLeakError as e:
        raise HTTPException(
            status_code=422,
            detail={"error": "pii_leak_risk", "types": e.leak_types},
        )

    write_process_log(
        session_id=out.session_id,
        step="api_sanitize",
        entity_count=len(out.entities),
        validation_result="warn" if out.warnings else "pass",
        flags=list(out.warnings),
        latency_ms=(time.time() - start) * 1000,
        output_dir=_get_audit_log_dir(),
    )
    return {
        "session_id": out.session_id,
        "original_text": out.original_text,
        "sanitized_text": out.sanitized_text,
        "entities": out.entities,
        "entity_type_counts": out.entity_type_counts,
        "section26": out.section26,
        "warnings": out.warnings,
    }
```

1e. Replace the `/api/reidentify` endpoint body:

```python
@app.post("/api/reidentify")
def reidentify(request: ReidentifyRequest):
    """Restore original PII via the core reverse mapper + output validation."""
    start = time.time()
    try:
        out = SERVICE.restore(request.session_id, request.text)
    except SessionExpiredError:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    write_process_log(
        session_id=request.session_id,
        step="api_reidentify",
        entity_count=out.replaced_count,
        validation_result="warn" if (out.leftover_tokens or out.warnings) else "pass",
        flags=[f"leftover:{t}" for t in out.leftover_tokens],
        latency_ms=(time.time() - start) * 1000,
        output_dir=_get_audit_log_dir(),
    )
    return {
        "restored_text": out.restored_text,
        "replaced": out.replaced,
        "replaced_count": out.replaced_count,
        "leftover_tokens": out.leftover_tokens,
        "warnings": out.warnings,
    }
```

1f. Replace the delete endpoint body:

```python
@app.delete("/api/session/{session_id}")
def delete_session(session_id: str):
    return {"deleted": SERVICE.drop(session_id)}
```

1g. Update the module docstring paragraph about `_SESSIONS` (lines 6-10) to say the map lives in `pii_redactor.session_service.SessionService` now.

- [ ] **Step 2: Run the frozen contract nets — NO edits allowed to these files**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_step11_api.py tests\test_api_hardening.py tests\test_e2e_examples.py -q`
Expected: all PASS. If a hardening TTL test fails, the `now_fn=lambda: _now()` late binding is wrong. If a shape test fails, the adapter mapping is wrong. Fix `app/server.py` or `session_service.py` — never the tests.

- [ ] **Step 3: Run the full suite**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest -q`
Expected: all PASS (~380 passed, 7 skipped)

- [ ] **Step 4: Grep to prove the second brain is gone**

Run: `git grep -n "_tokenize\|_make_surrogate\|_SESSIONS\b\|_TOKEN_LABEL" -- app tests pii_redactor`
Expected: no hits in `app/` (hits in this plan file / spec docs are fine)

- [ ] **Step 5: Commit**

```bash
git add app/server.py
git commit -m "refactor(server): endpoints are thin adapters over SessionService; delete _tokenize/_SESSIONS"
```

---

### Task 9: E2E multi-turn tests, guard sweep, docs

**Files:**
- Modify: `tests/test_e2e_examples.py` (append), `CLAUDE.md`, `docs/superpowers/specs/2026-07-10-post-competition-longterm-roadmap.md`
- Test: full suite + sweep script

**Interfaces:**
- Consumes: the live API via `fastapi.testclient` (same pattern as existing tests in `tests/test_e2e_examples.py` — read that file first and follow its client fixture/style).

- [ ] **Step 1: Write the failing e2e test** — append to `tests/test_e2e_examples.py` (adapt imports/fixtures to the file's existing style):

```python
def test_multi_turn_mask_restore_round_trip(client):
    """Extension flow across two turns in ONE session: tokens stay consistent
    and a combined AI reply restores every original."""
    t1 = client.post("/api/sanitize", json={"text": "ผมชื่อ สมชาย ใจดี เบอร์ 081-234-5678"}).json()
    t2 = client.post(
        "/api/sanitize",
        json={"text": "ย้ำเบอร์ 081-234-5678 และอีเมล somchai@example.com",
              "session_id": t1["session_id"]},
    ).json()
    assert t2["session_id"] == t1["session_id"]
    tok1 = next(e["token"] for e in t1["entities"] if e["data_type"] == "PHONE")
    tok2 = next(e["token"] for e in t2["entities"] if e["data_type"] == "PHONE")
    assert tok1 == tok2
    reply = t1["sanitized_text"] + "\n" + t2["sanitized_text"]
    r = client.post("/api/reidentify",
                    json={"session_id": t1["session_id"], "text": reply}).json()
    assert "081-234-5678" in r["restored_text"]
    assert "somchai@example.com" in r["restored_text"]
    assert "สมชาย ใจดี" in r["restored_text"]


def test_sanitize_mode_conflict_400(client):
    s = client.post("/api/sanitize", json={"text": "เบอร์ 081-234-5678"}).json()
    resp = client.post("/api/sanitize",
                       json={"text": "อีกข้อความ", "mode": "surrogate",
                             "session_id": s["session_id"]})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run to verify current state, then make pass**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest tests\test_e2e_examples.py -q`
Expected after Tasks 5-8: PASS immediately (the capability landed in Task 8). If FAIL, fix the service/adapter — the test encodes the spec.

- [ ] **Step 3: Guard false-positive sweep over real samples (verification, not CI)**

Save as `benchmark/sweep_web_guard.py` (committed — reusable verification tool):

```python
"""Salt-free sweep: run every sample file through the WEB path N times.

The service salts are random per session, so repeated runs sweep the same
space the PR #33/#34 flake hunts covered. Any OutboundLeakError here is a
guard false positive on the unified path.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pii_redactor.ingest.text_cleaner import clean
from pii_redactor.session_service import OutboundLeakError, SessionService

FILES = [
    "examples/prompts/01_sick_leave_email.txt",
    "examples/prompts/02_medical_consult.txt",
    "examples/prompts/03_bank_complaint.txt",
    "tests/sample_thai.txt",
]
RUNS = 30

failures = 0
for rel in FILES:
    text = clean(Path(rel).read_text(encoding="utf-8")).text
    for mode in ("token", "surrogate"):
        fail = 0
        for _ in range(RUNS):
            svc = SessionService()
            try:
                out = svc.sanitize(text, mode=mode)
                svc.restore(out.session_id, out.sanitized_text)
            except OutboundLeakError as e:
                fail += 1
        failures += fail
        print(f"{rel} [{mode}]: {fail}/{RUNS} guard failures")
print(f"TOTAL: {failures}")
sys.exit(1 if failures else 0)
```

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe benchmark\sweep_web_guard.py`
Expected: `TOTAL: 0`, exit 0. Non-zero = guard false positive on the new path; debug with the systematic-debugging skill before proceeding.

- [ ] **Step 4: Update docs**

In `CLAUDE.md`:
- The note at "Web API Endpoints" section end ("Note: the web API uses its own token/surrogate path (`_tokenize` + in-memory `_SESSIONS` ...) ... they are not unified.") → replace with: "Both the web API and the CLI now run on the same core: `pii_redactor/session_service.py` (`SessionService`) wraps `detect_all` → `anonymize(mode=token|surrogate)` → `leak_guard.scan_outbound_leaks` for `/api/sanitize`, and `reverse_map` → `validate_output` (warnings only, inbound) for `/api/reidentify`. Sessions: cap 200, idle TTL 1800s, vault null-byte-cleared on drop/evict. `/api/sanitize` accepts optional `session_id` for multi-turn token consistency and returns additive `warnings[]`; FP-grade residual leaks return HTTP 422."
- In the endpoints list, `/api/sanitize` entry: add `session_id` (optional) to the request fields and `warnings[]` to the response; `/api/reidentify` entry: add `warnings[]`.
- Key Modules table: add rows for `pii_redactor/session_service.py` ("Single brain behind the web API: session lifecycle + sanitize/restore over core components") and `pii_redactor/leak_guard.py` ("Shared outbound leak scan used by ai_client pre-send guard and SessionService").

In `docs/superpowers/specs/2026-07-10-post-competition-longterm-roadmap.md`, "อัปเดตสถานะ (2026-07-16)" section, add:

```markdown
- **Horizon-2 #8 Unify สองสมอง — เสร็จ (2026-07-16)**: `/api/sanitize`/`/api/reidentify` เดินผ่าน `pii_redactor/session_service.py` (SessionVault + leak guard + reverse_map + validator) contract v2 คงเดิม + `warnings[]`; `_tokenize`/`_SESSIONS` ถูกลบตาม kill-list; PyPI ยังไม่ทำ (แยกงาน)
```

- [ ] **Step 5: Full suite + commit**

Run: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest -q`
Expected: all PASS

```bash
git add tests/test_e2e_examples.py benchmark/sweep_web_guard.py CLAUDE.md docs/superpowers/specs/2026-07-10-post-competition-longterm-roadmap.md
git commit -m "test(e2e): multi-turn mask/restore + web-path guard sweep; docs reflect unified core"
```

---

## Final verification (after all tasks)

- [ ] Full suite: `$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe -m pytest -q` → all pass
- [ ] Contract files untouched: `git diff main -- tests/test_step11_api.py tests/test_api_hardening.py` → empty
- [ ] Sweep: `benchmark\sweep_web_guard.py` → TOTAL: 0
- [ ] Push branch, open PR to main titled `feat(core): unify web + CLI onto one brain (SessionService) — Horizon-2 #8`, body summarizing spec decisions; wait for CI green.
