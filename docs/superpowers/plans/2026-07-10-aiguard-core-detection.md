# aiguard-core Detection Implementation Plan (Part 1 of aiguard-core)

> **SUPERSEDED (2026-07-17) — อย่า execute plan นี้**
>
> Rust rewrite ถูกฆ่าถาวรตาม decision ข้อ 2 ใน
> [roadmap v2](../specs/2026-07-17-roadmap-v2-design.md) ไม่มีการ migrate ภาษาอีกต่อไป
> ไม่มีโค้ดจาก plan นี้ถูกเขียนจริง (ยืนยันแล้วว่าไม่มี `crates/` ใน repo)
> spec ที่คู่กันคือ [rust-rewrite-architecture-design](../specs/2026-07-10-rust-rewrite-architecture-design.md)
> ซึ่ง superseded เช่นกัน เก็บไว้เป็นบันทึกการตัดสินใจเท่านั้น

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `aiguard-core` Rust crate's detection foundation — workspace, core types, checksum/offset helpers, all format-preserving (FP) PII detectors with the scan's recall leaks fixed by construction, and the `NerEngine` trait plus a stub — as a self-contained, exhaustively tested library.

**Architecture:** A new Cargo workspace at the repo root with one member crate `crates/aiguard-core`. Detection is pure logic: regex candidate matching (standard `regex` crate, no lookaround) plus code-side digit-boundary checks and checksum validation. Spans are Unicode-scalar (char) offsets to match the Python v2 contract and pdfplumber alignment. Text-based detection (NER) enters only through a `NerEngine` trait so the crate compiles and tests with zero ML.

**Tech Stack:** Rust (edition 2021, rust-version 1.80+ for `std::sync::LazyLock`), `regex = "1"`. No other dependencies in this part.

**Scope note:** This is Part 1 of the `aiguard-core` sub-project (design doc `docs/superpowers/specs/2026-07-10-rust-rewrite-architecture-design.md`). It delivers detection only. Pseudonymization (token/surrogate, collision-safe), the vault, reverse mapping, and the output validator are Part 2 and depend on the types and detection this part produces.

## Global Constraints

- **No comments.** Not one line — no `//`, no `///` doc comments, no block comments — in any Rust source or test file. Descriptive names and tests are the only explanation. (User instruction, verbatim.)
- **Tests are the proof.** Every task follows the TDD cycle: write the failing test, run it and see it fail, implement, run it and see it pass, commit. Never mark a task done without running the test and seeing green.
- **Recall > precision.** When a pattern is ambiguous, prefer catching it (a false positive is acceptable; a missed PII is not).
- **Char offsets, not byte offsets.** `Entity.span` is `(start, end)` in Unicode scalar (char) offsets over the input `&str`, matching the Python contract. The `regex` crate returns byte offsets; every detector converts byte → char before storing a span. A Thai-prefixed value like `เลขบัตรประชาชน1101700230708` must yield span `(14, 27)`, not a byte span.
- **No regex lookaround.** The `regex` crate has no lookbehind/lookahead. Digit boundaries are enforced in code (`digit_bounded`), never with `(?<!\d)`/`(?!\d)`.
- **Rust version floor:** `rust-version = "1.80"` (for `std::sync::LazyLock`).
- **Workspace isolation:** the root workspace lists only `crates/aiguard-core` as a member and excludes `desktop` so the existing Tauri crate (which needs a placeholder sidecar binary to build) is never pulled into `cargo test`.

---

### Task 1: Workspace + crate scaffold

**Files:**
- Create: `Cargo.toml` (repo root workspace)
- Create: `crates/aiguard-core/Cargo.toml`
- Create: `crates/aiguard-core/src/lib.rs`
- Test: `crates/aiguard-core/src/lib.rs` (inline `#[cfg(test)]`)

**Interfaces:**
- Consumes: nothing.
- Produces: a buildable crate `aiguard-core` with `pub const CRATE_NAME: &str`.

- [ ] **Step 1: Write the failing test**

Create `crates/aiguard-core/src/lib.rs`:

```rust
pub const CRATE_NAME: &str = "aiguard-core";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn crate_name_is_set() {
        assert_eq!(CRATE_NAME, "aiguard-core");
    }
}
```

Create `crates/aiguard-core/Cargo.toml`:

```toml
[package]
name = "aiguard-core"
version = "0.1.0"
edition = "2021"
rust-version = "1.80"

[dependencies]
regex = "1"
```

Create root `Cargo.toml`:

```toml
[workspace]
resolver = "2"
members = ["crates/aiguard-core"]
exclude = ["desktop"]
```

- [ ] **Step 2: Run test to verify it fails, then passes trivially**

Run: `cargo test -p aiguard-core`
Expected: compiles and `crate_name_is_set` PASSES. If `cargo` reports it also tried to build `desktop`, the `exclude` line is missing — fix it and re-run.

- [ ] **Step 3: Commit**

```bash
git add Cargo.toml crates/aiguard-core/Cargo.toml crates/aiguard-core/src/lib.rs
git commit -m "feat(core): scaffold aiguard-core crate and root workspace"
```

---

### Task 2: Core types

**Files:**
- Create: `crates/aiguard-core/src/types.rs`
- Modify: `crates/aiguard-core/src/lib.rs` (add `pub mod types;`)
- Test: `crates/aiguard-core/src/types.rs` (inline `#[cfg(test)]`)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `pub enum RedactType { Fp, Tb }` (derives `Debug, Clone, Copy, PartialEq, Eq`)
  - `pub enum DataType { ThaiId, Phone, Email, BankAccount, CreditCard, DateOfBirth, VehiclePlate, Passport, StudentId, Iban, Name, Surname, Address, Date }` (derives `Debug, Clone, Copy, PartialEq, Eq`)
  - `pub struct Entity { pub entity_id: String, pub redact_type: RedactType, pub data_type: DataType, pub span: (usize, usize), pub score: f64, pub original_text: String }` (derives `Debug, Clone, PartialEq`)

- [ ] **Step 1: Write the failing test**

Create `crates/aiguard-core/src/types.rs`:

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RedactType {
    Fp,
    Tb,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DataType {
    ThaiId,
    Phone,
    Email,
    BankAccount,
    CreditCard,
    DateOfBirth,
    VehiclePlate,
    Passport,
    StudentId,
    Iban,
    Name,
    Surname,
    Address,
    Date,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Entity {
    pub entity_id: String,
    pub redact_type: RedactType,
    pub data_type: DataType,
    pub span: (usize, usize),
    pub score: f64,
    pub original_text: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn entity_holds_fields() {
        let e = Entity {
            entity_id: String::new(),
            redact_type: RedactType::Fp,
            data_type: DataType::ThaiId,
            span: (14, 27),
            score: 1.0,
            original_text: "1101700230708".to_string(),
        };
        assert_eq!(e.data_type, DataType::ThaiId);
        assert_eq!(e.span, (14, 27));
        assert_eq!(e.redact_type, RedactType::Fp);
    }
}
```

Add to `crates/aiguard-core/src/lib.rs` above the tests module:

```rust
pub mod types;
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cargo test -p aiguard-core types::`
Expected: `entity_holds_fields` PASSES.

- [ ] **Step 3: Commit**

```bash
git add crates/aiguard-core/src/types.rs crates/aiguard-core/src/lib.rs
git commit -m "feat(core): add Entity, DataType, RedactType"
```

---

### Task 3: Offset and boundary helpers

**Files:**
- Create: `crates/aiguard-core/src/textutil.rs`
- Modify: `crates/aiguard-core/src/lib.rs` (add `pub mod textutil;`)
- Test: `crates/aiguard-core/src/textutil.rs` (inline `#[cfg(test)]`)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `pub fn char_span(text: &str, byte_start: usize, byte_end: usize) -> (usize, usize)`
  - `pub fn digit_bounded(text: &str, byte_start: usize, byte_end: usize) -> bool` (true when the char immediately before `byte_start` is not an ASCII digit AND the char immediately after `byte_end` is not an ASCII digit)
  - `pub fn only_digits(s: &str) -> String`

- [ ] **Step 1: Write the failing test**

Create `crates/aiguard-core/src/textutil.rs`:

```rust
pub fn char_span(text: &str, byte_start: usize, byte_end: usize) -> (usize, usize) {
    let start = text[..byte_start].chars().count();
    let len = text[byte_start..byte_end].chars().count();
    (start, start + len)
}

pub fn digit_bounded(text: &str, byte_start: usize, byte_end: usize) -> bool {
    let before_ok = text[..byte_start]
        .chars()
        .next_back()
        .map_or(true, |c| !c.is_ascii_digit());
    let after_ok = text[byte_end..]
        .chars()
        .next()
        .map_or(true, |c| !c.is_ascii_digit());
    before_ok && after_ok
}

pub fn only_digits(s: &str) -> String {
    s.chars().filter(|c| c.is_ascii_digit()).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn char_span_counts_thai_prefix_as_chars() {
        let text = "เลขบัตรประชาชน1101700230708";
        let byte_start = "เลขบัตรประชาชน".len();
        let byte_end = text.len();
        assert_eq!(char_span(text, byte_start, byte_end), (14, 27));
    }

    #[test]
    fn digit_bounded_true_when_flanked_by_thai() {
        let text = "เลขบัตร1101700230708ครับ";
        let byte_start = "เลขบัตร".len();
        let byte_end = byte_start + "1101700230708".len();
        assert!(digit_bounded(text, byte_start, byte_end));
    }

    #[test]
    fn digit_bounded_false_when_followed_by_digit() {
        let text = "11017002307089";
        assert!(!digit_bounded(text, 0, 13));
    }

    #[test]
    fn only_digits_strips_separators_and_newlines() {
        assert_eq!(only_digits("110170\n0230708"), "1101700230708");
        assert_eq!(only_digits("081-234-5678"), "0812345678");
    }
}
```

Add to `lib.rs`:

```rust
pub mod textutil;
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cargo test -p aiguard-core textutil::`
Expected: all four PASS.

- [ ] **Step 3: Commit**

```bash
git add crates/aiguard-core/src/textutil.rs crates/aiguard-core/src/lib.rs
git commit -m "feat(core): char-offset and digit-boundary text helpers"
```

---

### Task 4: Checksums

**Files:**
- Create: `crates/aiguard-core/src/checksum.rs`
- Modify: `crates/aiguard-core/src/lib.rs` (add `pub mod checksum;`)
- Test: `crates/aiguard-core/src/checksum.rs` (inline `#[cfg(test)]`)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `pub fn is_valid_thai_id(digits: &str) -> bool` (mod-11: `weights = [13,12,11,10,9,8,7,6,5,4,3,2]`, `check = (11 - total % 11) % 10`, must equal 13th digit; exactly 13 ASCII digits)
  - `pub fn luhn_valid(digits: &str) -> bool`
  - `pub fn iban_valid(iban: &str) -> bool` (mod-97 == 1; letters A=10..Z=35; first 4 chars moved to end)
  - `pub fn date_sane(day: u32, month: u32) -> bool` (1..=31 and 1..=12)

- [ ] **Step 1: Write the failing test**

Create `crates/aiguard-core/src/checksum.rs`:

```rust
pub fn is_valid_thai_id(digits: &str) -> bool {
    let bytes = digits.as_bytes();
    if bytes.len() != 13 || !digits.chars().all(|c| c.is_ascii_digit()) {
        return false;
    }
    let weights = [13u32, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2];
    let mut total = 0u32;
    for i in 0..12 {
        total += (bytes[i] - b'0') as u32 * weights[i];
    }
    let check = (11 - (total % 11)) % 10;
    check == (bytes[12] - b'0') as u32
}

pub fn luhn_valid(digits: &str) -> bool {
    if digits.is_empty() || !digits.chars().all(|c| c.is_ascii_digit()) {
        return false;
    }
    let mut total = 0u32;
    for (i, ch) in digits.chars().rev().enumerate() {
        let mut n = ch.to_digit(10).unwrap();
        if i % 2 == 1 {
            n *= 2;
            if n > 9 {
                n -= 9;
            }
        }
        total += n;
    }
    total % 10 == 0
}

pub fn iban_valid(iban: &str) -> bool {
    if iban.len() < 4 || !iban.chars().all(|c| c.is_ascii_alphanumeric()) {
        return false;
    }
    let rearranged: String = format!("{}{}", &iban[4..], &iban[..4]);
    let mut expanded = String::new();
    for ch in rearranged.chars() {
        if ch.is_ascii_alphabetic() {
            let v = ch.to_ascii_uppercase() as u32 - 'A' as u32 + 10;
            expanded.push_str(&v.to_string());
        } else if ch.is_ascii_digit() {
            expanded.push(ch);
        } else {
            return false;
        }
    }
    let mut remainder = 0u32;
    for ch in expanded.chars() {
        remainder = (remainder * 10 + ch.to_digit(10).unwrap()) % 97;
    }
    remainder == 1
}

pub fn date_sane(day: u32, month: u32) -> bool {
    (1..=31).contains(&day) && (1..=12).contains(&month)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn thai_id_accepts_known_valid() {
        assert!(is_valid_thai_id("1101700230708"));
    }

    #[test]
    fn thai_id_rejects_bad_checksum_and_length() {
        assert!(!is_valid_thai_id("1101700230709"));
        assert!(!is_valid_thai_id("110170023070"));
        assert!(!is_valid_thai_id("11017002307o8"));
    }

    #[test]
    fn luhn_accepts_valid_card() {
        assert!(luhn_valid("4111111111111111"));
        assert!(!luhn_valid("4111111111111112"));
    }

    #[test]
    fn iban_accepts_valid_and_rejects_invalid() {
        assert!(iban_valid("GB82WEST12345698765432"));
        assert!(!iban_valid("GB82WEST12345698765433"));
    }

    #[test]
    fn date_sanity_bounds() {
        assert!(date_sane(31, 12));
        assert!(!date_sane(0, 12));
        assert!(!date_sane(31, 13));
    }
}
```

Add to `lib.rs`:

```rust
pub mod checksum;
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cargo test -p aiguard-core checksum::`
Expected: all five PASS. If `thai_id_accepts_known_valid` fails, the mod-11 formula was transcribed wrong — recheck weights and `(11 - total % 11) % 10`.

- [ ] **Step 3: Commit**

```bash
git add crates/aiguard-core/src/checksum.rs crates/aiguard-core/src/lib.rs
git commit -m "feat(core): thai-id mod11, luhn, iban mod97, date sanity checksums"
```

---

### Task 5: Detector scaffolding + checksum-gated numeric detectors (THAI_ID, CREDIT_CARD)

**Files:**
- Create: `crates/aiguard-core/src/detect/mod.rs`
- Create: `crates/aiguard-core/src/detect/numeric.rs`
- Modify: `crates/aiguard-core/src/lib.rs` (add `pub mod detect;`)
- Test: `crates/aiguard-core/src/detect/numeric.rs` (inline `#[cfg(test)]`)

**Interfaces:**
- Consumes: `types::{Entity, DataType, RedactType}`, `textutil::{char_span, digit_bounded, only_digits}`, `checksum::{is_valid_thai_id, luhn_valid}`.
- Produces:
  - `pub(crate) fn fp_entity(data_type: DataType, text: &str, byte_start: usize, byte_end: usize, score: f64) -> Entity`
  - `pub fn detect_thai_id(text: &str) -> Vec<Entity>`
  - `pub fn detect_credit_card(text: &str) -> Vec<Entity>`

Both numeric detectors use candidate regex `\d(?:[-.\s]?\d){N}` (N=12 for ID, N=15 for card), enforce `digit_bounded`, strip separators with `only_digits`, and gate on the checksum. This matches values split across a newline or grouped nonstandardly (the scan's line-break and dash-grouping leaks) because separators are allowed between every digit.

- [ ] **Step 1: Write the failing test**

Create `crates/aiguard-core/src/detect/mod.rs`:

```rust
pub mod numeric;
```

Create `crates/aiguard-core/src/detect/numeric.rs`:

```rust
use std::sync::LazyLock;

use regex::Regex;

use crate::checksum::{is_valid_thai_id, luhn_valid};
use crate::textutil::{char_span, digit_bounded, only_digits};
use crate::types::{DataType, Entity, RedactType};

pub(crate) fn fp_entity(
    data_type: DataType,
    text: &str,
    byte_start: usize,
    byte_end: usize,
    score: f64,
) -> Entity {
    let (start, end) = char_span(text, byte_start, byte_end);
    Entity {
        entity_id: String::new(),
        redact_type: RedactType::Fp,
        data_type,
        span: (start, end),
        score,
        original_text: text[byte_start..byte_end].to_string(),
    }
}

static RE_ID: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\d(?:[-.\s]?\d){12}").unwrap());
static RE_CARD: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\d(?:[-.\s]?\d){15}").unwrap());

pub fn detect_thai_id(text: &str) -> Vec<Entity> {
    let mut out = Vec::new();
    for m in RE_ID.find_iter(text) {
        if !digit_bounded(text, m.start(), m.end()) {
            continue;
        }
        let raw = only_digits(m.as_str());
        if raw.len() == 13 && is_valid_thai_id(&raw) {
            out.push(fp_entity(DataType::ThaiId, text, m.start(), m.end(), 1.0));
        }
    }
    out
}

pub fn detect_credit_card(text: &str) -> Vec<Entity> {
    let mut out = Vec::new();
    for m in RE_CARD.find_iter(text) {
        if !digit_bounded(text, m.start(), m.end()) {
            continue;
        }
        let raw = only_digits(m.as_str());
        if raw.len() == 16 && luhn_valid(&raw) {
            out.push(fp_entity(DataType::CreditCard, text, m.start(), m.end(), 1.0));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn thai_id_glued_to_thai_script() {
        let e = detect_thai_id("เลขบัตรประชาชน1101700230708");
        assert_eq!(e.len(), 1);
        assert_eq!(e[0].data_type, DataType::ThaiId);
        assert_eq!(e[0].span, (14, 27));
        assert_eq!(e[0].original_text, "1101700230708");
    }

    #[test]
    fn thai_id_split_across_newline() {
        let e = detect_thai_id("เลขบัตร 110170\n0230708");
        assert_eq!(e.len(), 1);
        assert_eq!(only_digits(&e[0].original_text), "1101700230708");
    }

    #[test]
    fn thai_id_nonstandard_dash_grouping() {
        let e = detect_thai_id("เลขบัตรประชาชน1-1017-0023-07-08");
        assert_eq!(e.len(), 1);
    }

    #[test]
    fn thai_id_rejects_bad_checksum() {
        assert!(detect_thai_id("1101700230709").is_empty());
    }

    #[test]
    fn thai_id_not_matched_inside_longer_run() {
        assert!(detect_thai_id("11017002307080000").is_empty());
    }

    #[test]
    fn credit_card_spaced_and_glued() {
        let e = detect_credit_card("บัตรเครดิต4111 1111 1111 1111");
        assert_eq!(e.len(), 1);
        assert_eq!(e[0].data_type, DataType::CreditCard);
    }
}
```

Add to `lib.rs`:

```rust
pub mod detect;
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cargo test -p aiguard-core detect::numeric::`
Expected: all six PASS. `thai_id_split_across_newline` and `thai_id_nonstandard_dash_grouping` are the scan's confirmed leaks — they MUST pass.

- [ ] **Step 3: Commit**

```bash
git add crates/aiguard-core/src/detect crates/aiguard-core/src/lib.rs
git commit -m "feat(core): THAI_ID and CREDIT_CARD detectors with separator-tolerant matching"
```

---

### Task 6: PHONE detector (fixes landline-9-digit, dot separators, parenthesized +66)

**Files:**
- Create: `crates/aiguard-core/src/detect/phone.rs`
- Modify: `crates/aiguard-core/src/detect/mod.rs` (add `pub mod phone;`)
- Test: `crates/aiguard-core/src/detect/phone.rs` (inline `#[cfg(test)]`)

**Interfaces:**
- Consumes: `detect::numeric::fp_entity`, `textutil::{digit_bounded, only_digits}`, `types::{Entity, DataType}`.
- Produces: `pub fn detect_phone(text: &str) -> Vec<Entity>`

Approach: one broad candidate regex captures a token that starts with `(+66)`, `+66`, `(0)`, or `0` followed by digits and separators; code normalizes to the national 0-form and classifies. National number must be 9 digits (landline, second digit 2-7) or 10 digits (mobile, second digit 6-9). This fixes three confirmed leaks: 9-digit landline `02-123-4567`, dot-separated `081.234.5678`, and parenthesized `(+66) 81 234 5678` / `+66 (0) 81 234 5678`.

- [ ] **Step 1: Write the failing test**

Create `crates/aiguard-core/src/detect/phone.rs`:

```rust
use std::sync::LazyLock;

use regex::Regex;

use crate::detect::numeric::fp_entity;
use crate::textutil::digit_bounded;
use crate::types::{DataType, Entity};

static RE_MOBILE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"0[6-9](?:[-.\s]?\d){8}").unwrap());
static RE_LANDLINE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"0[2-7](?:[-.\s]?\d){7}").unwrap());
static RE_INTL: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\(?\+66\)?[-.\s]?(?:\(0\)[-.\s]?)?\d(?:[-.\s]?\d){7,8}").unwrap());

pub fn detect_phone(text: &str) -> Vec<Entity> {
    let mut out = Vec::new();
    for re in [&*RE_MOBILE, &*RE_LANDLINE, &*RE_INTL] {
        for m in re.find_iter(text) {
            if digit_bounded(text, m.start(), m.end()) {
                out.push(fp_entity(DataType::Phone, text, m.start(), m.end(), 1.0));
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::textutil::only_digits;

    fn types(text: &str) -> Vec<String> {
        detect_phone(text)
            .iter()
            .map(|e| only_digits(&e.original_text))
            .collect()
    }

    #[test]
    fn mobile_forms() {
        assert_eq!(types("โทร0812345678"), vec!["0812345678"]);
        assert_eq!(types("081-234-5678"), vec!["0812345678"]);
        assert_eq!(types("081.234.5678"), vec!["0812345678"]);
    }

    #[test]
    fn landline_nine_digits() {
        assert_eq!(types("โทร 02-123-4567"), vec!["021234567"]);
        assert_eq!(types("ติดต่อ 02 123 4567 ครับ"), vec!["021234567"]);
    }

    #[test]
    fn intl_plus66_forms() {
        assert_eq!(detect_phone("+66 81 234 5678").len(), 1);
        assert_eq!(detect_phone("+66812345678").len(), 1);
        assert_eq!(detect_phone("(+66) 81 234 5678").len(), 1);
        assert_eq!(detect_phone("+66 (0) 81 234 5678").len(), 1);
    }

    #[test]
    fn rejects_random_eight_digit_run() {
        assert!(detect_phone("รหัส 12345678").is_empty());
    }
}
```

Add to `crates/aiguard-core/src/detect/mod.rs`:

```rust
pub mod phone;
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cargo test -p aiguard-core detect::phone::`
Expected: all four PASS. `landline_nine_digits` and the paren cases in `intl_plus66_forms` are the scan's confirmed leaks — they MUST pass.

- [ ] **Step 3: Commit**

```bash
git add crates/aiguard-core/src/detect/phone.rs crates/aiguard-core/src/detect/mod.rs
git commit -m "feat(core): PHONE detector fixing 9-digit landline, dot separators, (+66) forms"
```

---

### Task 7: EMAIL detector (catches Thai-glued addresses)

**Files:**
- Create: `crates/aiguard-core/src/detect/email.rs`
- Modify: `crates/aiguard-core/src/detect/mod.rs` (add `pub mod email;`)
- Test: `crates/aiguard-core/src/detect/email.rs` (inline `#[cfg(test)]`)

**Interfaces:**
- Consumes: `detect::numeric::fp_entity`, `types::{Entity, DataType}`.
- Produces: `pub fn detect_email(text: &str) -> Vec<Entity>`

The regex must NOT use `\b` (Rust `\b` is Unicode-aware, so a Thai letter glued to the local part suppresses the boundary — the scan's confirmed leak). The local/domain character classes themselves bound the match; a Thai prefix like `อีเมล` is not in the local-part class, so matching still starts at the first local-part char.

- [ ] **Step 1: Write the failing test**

Create `crates/aiguard-core/src/detect/email.rs`:

```rust
use std::sync::LazyLock;

use regex::Regex;

use crate::detect::numeric::fp_entity;
use crate::types::{DataType, Entity};

static RE_EMAIL: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}").unwrap()
});

pub fn detect_email(text: &str) -> Vec<Entity> {
    let mut out = Vec::new();
    for m in RE_EMAIL.find_iter(text) {
        out.push(fp_entity(DataType::Email, text, m.start(), m.end(), 1.0));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plain_email() {
        let e = detect_email("ติดต่อ somchai@example.com นะ");
        assert_eq!(e.len(), 1);
        assert_eq!(e[0].original_text, "somchai@example.com");
        assert_eq!(e[0].data_type, DataType::Email);
    }

    #[test]
    fn email_glued_to_thai_prefix() {
        let e = detect_email("อีเมลsomchai@example.com");
        assert_eq!(e.len(), 1);
        assert_eq!(e[0].original_text, "somchai@example.com");
    }
}
```

Add to `crates/aiguard-core/src/detect/mod.rs`:

```rust
pub mod email;
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cargo test -p aiguard-core detect::email::`
Expected: both PASS. `email_glued_to_thai_prefix` is the scan's confirmed leak.

- [ ] **Step 3: Commit**

```bash
git add crates/aiguard-core/src/detect/email.rs crates/aiguard-core/src/detect/mod.rs
git commit -m "feat(core): EMAIL detector that catches Thai-glued addresses"
```

---

### Task 8: Remaining detectors (BANK_ACCOUNT, DATE_OF_BIRTH, IBAN, VEHICLE_PLATE, PASSPORT, STUDENT_ID)

**Files:**
- Create: `crates/aiguard-core/src/detect/misc.rs`
- Modify: `crates/aiguard-core/src/detect/mod.rs` (add `pub mod misc;`)
- Test: `crates/aiguard-core/src/detect/misc.rs` (inline `#[cfg(test)]`)

**Interfaces:**
- Consumes: `detect::numeric::fp_entity`, `textutil::{digit_bounded, only_digits}`, `checksum::{iban_valid, date_sane}`, `types::{Entity, DataType}`.
- Produces:
  - `pub fn detect_bank_account(text: &str) -> Vec<Entity>`
  - `pub fn detect_date_of_birth(text: &str) -> Vec<Entity>`
  - `pub fn detect_iban(text: &str) -> Vec<Entity>`
  - `pub fn detect_vehicle_plate(text: &str) -> Vec<Entity>`
  - `pub fn detect_passport(text: &str) -> Vec<Entity>`
  - `pub fn detect_student_id(text: &str) -> Vec<Entity>`

- [ ] **Step 1: Write the failing test**

Create `crates/aiguard-core/src/detect/misc.rs`:

```rust
use std::sync::LazyLock;

use regex::Regex;

use crate::checksum::{date_sane, iban_valid};
use crate::detect::numeric::fp_entity;
use crate::textutil::{digit_bounded, only_digits};
use crate::types::{DataType, Entity};

static RE_BANK1: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\d{3}[-.\s]?\d[-.\s]?\d{5}[-.\s]?\d").unwrap());
static RE_BANK2: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\d{7}[-.\s]?\d{3}").unwrap());
static RE_DATE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\d{1,2}[/\-]\d{1,2}[/\-](?:\d{4}|\d{2})").unwrap());
static RE_IBAN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[A-Z]{2}\d{2}[A-Z0-9]{4,30}").unwrap());
static RE_PLATE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[ก-ฮ]{1,3}\s*\d{1,4}").unwrap());
static RE_PASSPORT_TH: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[A-Z]{2}\d{7}").unwrap());
static RE_PASSPORT: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[A-Z]{1,2}\d{6,9}").unwrap());
static RE_STUDENT: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\d{8,12}").unwrap());
static RE_THAI_CHAR: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[ก-๿]").unwrap());

fn numeric_bounded(text: &str, m: &regex::Match) -> bool {
    digit_bounded(text, m.start(), m.end())
}

pub fn detect_bank_account(text: &str) -> Vec<Entity> {
    let mut out = Vec::new();
    for re in [&*RE_BANK1, &*RE_BANK2] {
        for m in re.find_iter(text) {
            if numeric_bounded(text, &m) {
                out.push(fp_entity(DataType::BankAccount, text, m.start(), m.end(), 1.0));
            }
        }
    }
    out
}

pub fn detect_date_of_birth(text: &str) -> Vec<Entity> {
    let mut out = Vec::new();
    for m in RE_DATE.find_iter(text) {
        if !numeric_bounded(text, &m) {
            continue;
        }
        let parts: Vec<&str> = m.as_str().split(['/', '-']).collect();
        if parts.len() == 3 {
            if let (Ok(day), Ok(month)) = (parts[0].parse::<u32>(), parts[1].parse::<u32>()) {
                if date_sane(day, month) {
                    out.push(fp_entity(DataType::DateOfBirth, text, m.start(), m.end(), 1.0));
                }
            }
        }
    }
    out
}

pub fn detect_iban(text: &str) -> Vec<Entity> {
    let mut out = Vec::new();
    for m in RE_IBAN.find_iter(text) {
        if iban_valid(m.as_str()) {
            out.push(fp_entity(DataType::Iban, text, m.start(), m.end(), 1.0));
        }
    }
    out
}

pub fn detect_vehicle_plate(text: &str) -> Vec<Entity> {
    let mut out = Vec::new();
    for m in RE_PLATE.find_iter(text) {
        let before = text[..m.start()].chars().next_back();
        if before.map_or(false, |c| RE_THAI_CHAR.is_match(&c.to_string())) {
            continue;
        }
        out.push(fp_entity(DataType::VehiclePlate, text, m.start(), m.end(), 0.9));
    }
    out
}

pub fn detect_passport(text: &str) -> Vec<Entity> {
    let mut out = Vec::new();
    for re in [&*RE_PASSPORT_TH, &*RE_PASSPORT] {
        for m in re.find_iter(text) {
            out.push(fp_entity(DataType::Passport, text, m.start(), m.end(), 1.0));
        }
    }
    out
}

pub fn detect_student_id(text: &str) -> Vec<Entity> {
    let mut out = Vec::new();
    for m in RE_STUDENT.find_iter(text) {
        if numeric_bounded(text, &m) {
            let _ = only_digits(m.as_str());
            out.push(fp_entity(DataType::StudentId, text, m.start(), m.end(), 0.8));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bank_account_glued() {
        assert_eq!(detect_bank_account("เลขบัญชี123-4-56789-0").len(), 1);
        assert_eq!(detect_bank_account("บัญชี1234567890").len(), 1);
    }

    #[test]
    fn date_of_birth_valid_and_invalid() {
        assert_eq!(detect_date_of_birth("เกิด 05/12/1990").len(), 1);
        assert!(detect_date_of_birth("รหัส 99/99/9999").is_empty());
    }

    #[test]
    fn iban_valid_only() {
        assert_eq!(detect_iban("IBAN GB82WEST12345698765432 ").len(), 1);
    }

    #[test]
    fn student_id_bare_run() {
        let e = detect_student_id("รหัสนักศึกษา 6012345678");
        assert_eq!(e.len(), 1);
        assert_eq!(e[0].score, 0.8);
    }

    #[test]
    fn passport_forms() {
        assert_eq!(detect_passport("AB1234567").len(), 1);
    }
}
```

Add to `crates/aiguard-core/src/detect/mod.rs`:

```rust
pub mod misc;
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cargo test -p aiguard-core detect::misc::`
Expected: all five PASS.

- [ ] **Step 3: Commit**

```bash
git add crates/aiguard-core/src/detect/misc.rs crates/aiguard-core/src/detect/mod.rs
git commit -m "feat(core): bank, date, iban, plate, passport, student-id detectors"
```

---

### Task 9: Dedup + `detect_fp` assembly

**Files:**
- Modify: `crates/aiguard-core/src/detect/mod.rs` (add `dedupe` and `detect_fp`)
- Test: `crates/aiguard-core/src/detect/mod.rs` (inline `#[cfg(test)]`)

**Interfaces:**
- Consumes: all `detect_*` functions, `types::Entity`.
- Produces:
  - `pub fn detect_fp(text: &str) -> Vec<Entity>` (runs every FP detector, dedupes overlapping spans preferring higher score then earlier start, drops spans shorter than 2 chars, returns sorted by span start)

Dedup rule (ported from `_deduplicate`): sort by `(span.0 asc, score desc)`; keep an entity only if its span does not overlap any already-kept span and its char length is >= 2; return sorted by span start.

- [ ] **Step 1: Write the failing test**

Add to `crates/aiguard-core/src/detect/mod.rs` (below the `pub mod` lines):

```rust
use crate::types::Entity;

pub fn detect_fp(text: &str) -> Vec<Entity> {
    let mut all = Vec::new();
    all.extend(numeric::detect_thai_id(text));
    all.extend(numeric::detect_credit_card(text));
    all.extend(misc::detect_iban(text));
    all.extend(email::detect_email(text));
    all.extend(phone::detect_phone(text));
    all.extend(misc::detect_bank_account(text));
    all.extend(misc::detect_date_of_birth(text));
    all.extend(misc::detect_vehicle_plate(text));
    all.extend(misc::detect_passport(text));
    all.extend(misc::detect_student_id(text));
    dedupe(all)
}

fn dedupe(mut entities: Vec<Entity>) -> Vec<Entity> {
    entities.sort_by(|a, b| {
        a.span
            .0
            .cmp(&b.span.0)
            .then(b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal))
    });
    let mut kept: Vec<Entity> = Vec::new();
    for ent in entities {
        if ent.span.1 - ent.span.0 < 2 {
            continue;
        }
        let overlaps = kept
            .iter()
            .any(|k| !(ent.span.1 <= k.span.0 || ent.span.0 >= k.span.1));
        if !overlaps {
            kept.push(ent);
        }
    }
    kept.sort_by_key(|e| e.span.0);
    kept
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::DataType;

    #[test]
    fn student_id_yields_to_higher_score_phone() {
        let entities = detect_fp("โทร0812345678");
        let phones: Vec<&Entity> = entities
            .iter()
            .filter(|e| e.data_type == DataType::Phone)
            .collect();
        assert_eq!(phones.len(), 1);
        assert!(!entities.iter().any(|e| e.data_type == DataType::StudentId));
    }

    #[test]
    fn multiple_distinct_entities_all_kept() {
        let text = "เลขบัตรประชาชน 1101700230705 อีเมล somchai@example.com โทร 081-234-5678";
        let entities = detect_fp(text);
        let kinds: Vec<DataType> = entities.iter().map(|e| e.data_type).collect();
        assert!(kinds.contains(&DataType::ThaiId));
        assert!(kinds.contains(&DataType::Email));
        assert!(kinds.contains(&DataType::Phone));
    }

    #[test]
    fn spans_sorted_ascending() {
        let entities = detect_fp("อีเมล a@b.co โทร 0812345678");
        for w in entities.windows(2) {
            assert!(w[0].span.0 <= w[1].span.0);
        }
    }
}
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cargo test -p aiguard-core detect::tests`
Expected: all three PASS. `student_id_yields_to_higher_score_phone` proves the STUDENT_ID catch-all no longer mislabels a mobile number.

- [ ] **Step 3: Commit**

```bash
git add crates/aiguard-core/src/detect/mod.rs
git commit -m "feat(core): detect_fp assembly with overlap dedup and span chokepoint"
```

---

### Task 10: `NerEngine` trait + stub + `detect` facade

**Files:**
- Create: `crates/aiguard-core/src/ner.rs`
- Modify: `crates/aiguard-core/src/lib.rs` (add `pub mod ner;` and a `detect` facade)
- Test: `crates/aiguard-core/src/ner.rs` (inline `#[cfg(test)]`) and `crates/aiguard-core/src/lib.rs`

**Interfaces:**
- Consumes: `types::Entity`, `detect::detect_fp`.
- Produces:
  - `pub trait NerEngine { fn detect_tb(&self, text: &str) -> Vec<Entity>; }`
  - `pub struct StubNer;` implementing `NerEngine` (returns empty)
  - `pub fn detect(text: &str, ner: &dyn NerEngine) -> Vec<Entity>` (FP entities followed by TB entities from the engine)

- [ ] **Step 1: Write the failing test**

Create `crates/aiguard-core/src/ner.rs`:

```rust
use crate::types::Entity;

pub trait NerEngine {
    fn detect_tb(&self, text: &str) -> Vec<Entity>;
}

pub struct StubNer;

impl NerEngine for StubNer {
    fn detect_tb(&self, _text: &str) -> Vec<Entity> {
        Vec::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stub_returns_empty() {
        let ner = StubNer;
        assert!(ner.detect_tb("ผมชื่อสมชาย").is_empty());
    }
}
```

Add to `crates/aiguard-core/src/lib.rs` (above the tests module):

```rust
pub mod ner;

pub fn detect(text: &str, ner: &dyn ner::NerEngine) -> Vec<types::Entity> {
    let mut out = detect::detect_fp(text);
    out.extend(ner.detect_tb(text));
    out
}
```

Add a test to the `lib.rs` tests module:

```rust
    #[test]
    fn detect_combines_fp_and_ner() {
        let entities = detect("โทร 0812345678", &ner::StubNer);
        assert_eq!(entities.len(), 1);
        assert_eq!(entities[0].data_type, types::DataType::Phone);
    }
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cargo test -p aiguard-core`
Expected: the whole crate's tests PASS (all tasks). `detect_combines_fp_and_ner` and `stub_returns_empty` are new.

- [ ] **Step 3: Commit**

```bash
git add crates/aiguard-core/src/ner.rs crates/aiguard-core/src/lib.rs
git commit -m "feat(core): NerEngine trait, StubNer, and detect facade"
```

---

### Task 11: Full-suite green + parity spot-check against Python

**Files:**
- Test: `crates/aiguard-core/tests/parity.rs` (integration test)

**Interfaces:**
- Consumes: `aiguard_core::detect_fp`.
- Produces: nothing (verification only).

This locks in the recall-leak fixes as a single adversarial corpus and confirms the crate builds clean with no warnings.

- [ ] **Step 1: Write the failing test**

Create `crates/aiguard-core/tests/parity.rs`:

```rust
use aiguard_core::detect_fp;
use aiguard_core::types::DataType;

fn kinds(text: &str) -> Vec<DataType> {
    detect_fp(text).into_iter().map(|e| e.data_type).collect()
}

#[test]
fn scan_confirmed_leaks_are_closed() {
    assert!(kinds("เลขบัตรประชาชน1101700230708").contains(&DataType::ThaiId));
    assert!(kinds("เลขบัตร 110170\n0230708").contains(&DataType::ThaiId));
    assert!(kinds("เลขบัตรประชาชน1-1017-0023-07-08").contains(&DataType::ThaiId));
    assert!(kinds("โทร 02-123-4567").contains(&DataType::Phone));
    assert!(kinds("081.234.5678").contains(&DataType::Phone));
    assert!(kinds("(+66) 81 234 5678").contains(&DataType::Phone));
    assert!(kinds("+66 (0) 81 234 5678").contains(&DataType::Phone));
    assert!(kinds("อีเมลsomchai@example.com").contains(&DataType::Email));
}

#[test]
fn plus66_mobile_not_labeled_student_id() {
    let k = kinds("+66812345678");
    assert!(k.contains(&DataType::Phone));
    assert!(!k.contains(&DataType::StudentId));
}
```

- [ ] **Step 2: Run the full suite with warnings denied**

Run: `cargo test -p aiguard-core`
Then run: `cargo build -p aiguard-core 2>&1 | grep -i warning; test $? -eq 1`
Expected: all tests PASS; the second command exits 0 (meaning `grep` found no warning lines). If any warning appears, fix it (unused import, dead code) before committing.

- [ ] **Step 3: Commit**

```bash
git add crates/aiguard-core/tests/parity.rs
git commit -m "test(core): adversarial parity corpus locking the scan's recall-leak fixes"
```

---

## Self-Review

**Spec coverage** (against `aiguard-core` in the design doc's "Sub-project #1" section):
- `detect/fp` regex+checksum for all listed data_types — Tasks 4-9 (THAI_ID, CREDIT_CARD, PHONE, EMAIL, BANK_ACCOUNT, DATE_OF_BIRTH, IBAN, VEHICLE_PLATE, PASSPORT, STUDENT_ID). Covered.
- digit-boundary lookaround replacement — Task 3 `digit_bounded`, applied in every numeric detector. Covered.
- recall-leak fixes (landline-9, (+66) parens, glued email, line-break ID) — Tasks 5, 6, 7 with dedicated tests; Task 11 corpus. Covered.
- span < 2 chokepoint + dedup — Task 9. Covered.
- `NerEngine` trait + stub so core has no ML dependency — Task 10. Covered.
- char offsets — Global Constraint + Task 3 + Task 5 span assertion `(14, 27)`. Covered.
- Deferred to Part 2 (not in this plan): pseudonymize (token/surrogate, collision-safe), vault (TTL, snapshot/restore), reverse mapper, output validator, the PreSendValidation and Thai-truncation fixes (those live in the validator). Flagged in the Scope note. This is intentional decomposition, not a gap.

**Placeholder scan:** no TBD/TODO; every code step has complete code; no "add error handling" hand-waves. Clean.

**Type consistency:** `Entity`/`DataType`/`RedactType` defined in Task 2 are used unchanged in Tasks 5-11; `fp_entity` defined in Task 5 is consumed by Tasks 6-8; `detect_fp` (Task 9) consumed by Tasks 10-11; `NerEngine` (Task 10) matches the design doc's trait name. Consistent.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-10-aiguard-core-detection.md`.
