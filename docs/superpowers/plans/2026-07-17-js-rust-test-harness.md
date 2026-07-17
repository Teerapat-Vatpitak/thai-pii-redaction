# JS/Rust Test Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the untested 1,400 lines of extension JS and the Tauri sidecar kill path under a real test harness (vitest+jsdom for JS, cargo tests for the kill sequence) wired into CI — Playwright live-DOM fixtures and the selector-drift badge are explicitly deferred.

**Architecture:** `extension/sites.js` gets an additive CommonJS export shim + a `selectFor(hostname)` extraction (browser behavior byte-identical); tests exercise every site config against hand-written HTML fixtures under jsdom. `desktop/src-tauri/src/sidecar.rs` gets extract-function refactors (`shutdown_request`, `kill_with(state, addr)`) so the shutdown-then-force-kill sequence is testable against a std TcpListener mock and a real victim process. New CI job runs vitest on ubuntu. Spec: `docs/superpowers/specs/2026-07-17-js-rust-test-harness-design.md`.

**Tech Stack:** Node 24 / npm 11 (present locally), vitest + jsdom (dev-only, root package.json), Rust std only (no new crates).

## Global Constraints

- Run Python-free: this plan touches NO Python files (`git diff --stat` must show none). Frozen as ever: `tests/test_step11_api.py`, `tests/test_api_hardening.py`, `CLAUDE.md`.
- **Commit messages MUST NOT contain any `Co-Authored-By: Claude ...` trailer.**
- Browser behavior of `extension/*.js` must be byte-path-identical: the shim is additive (`if (typeof module !== "undefined" && module.exports)`), the hostname selection result is unchanged for every hostname, and NO existing selector string changes.
- No new Rust dependencies; no bundler/transpiler for JS; vitest+jsdom are the only new npm dev-dependencies (plus their transitive lockfile entries).
- Work on branch `feat/js-rust-test-harness` (exists; contains the spec commit).
- Bash commands from repo root `C:\Users\teera\dev\thai-pii-redaction`; node v24 + npm 11 + cargo 1.97 verified present.

---

### Task 1: JS toolchain + sites.js export shim + routing tests

**Files:**
- Create: `package.json`, `vitest.config.js`, `extension/tests/sites.routing.test.js`
- Modify: `extension/sites.js` (bottom of the IIFE only, lines ~234-245), `.gitignore` (add `node_modules/`)
- Generated: `package-lock.json` (commit it)

**Interfaces:**
- Produces (Task 2 relies on): requiring/importing `extension/sites.js` under vitest's jsdom environment yields `module.exports = { chatgpt, claude, gemini, grok, perplexity, zai, generic, selectFor, helpers: { visible, isTextField, pickVisible, genericComposer, readComposer, writeComposer } }`. `selectFor(hostname: string)` returns the same config object the old inline code selected. `npm run test:js` runs vitest.

- [ ] **Step 1: Toolchain files**

`package.json` (root):

```json
{
  "name": "aiguard-dev",
  "private": true,
  "description": "Dev-only JS test harness for the AI Guard extension (vitest+jsdom). Not shipped.",
  "scripts": {
    "test:js": "vitest run"
  },
  "devDependencies": {
    "jsdom": "^26.0.0",
    "vitest": "^3.0.0"
  }
}
```

`vitest.config.js` (root):

```js
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["extension/tests/**/*.test.js"],
  },
});
```

Append `node_modules/` to `.gitignore` (check it is not already there first). Run `npm install` and confirm `package-lock.json` appears.

- [ ] **Step 2: Write the failing routing tests** — create `extension/tests/sites.routing.test.js`:

```js
// sites.js selects a per-host config at load time; selectFor(hostname) is the
// extracted, testable form of that routing. jsdom quirks this suite relies on:
// getBoundingClientRect() is all-zero (visible() -> false, pickVisible falls
// back to list[0]) and document.execCommand is undefined (writeComposer takes
// its fallback paths). Both fallbacks are real code paths worth pinning.
import { describe, expect, test } from "vitest";
import sites from "../sites.js";

describe("hostname routing (selectFor)", () => {
  const cases = [
    ["claude.ai", "claude"],
    ["gemini.google.com", "gemini"],
    ["grok.com", "grok"],
    ["www.perplexity.ai", "perplexity"],
    ["chat.z.ai", "zai"],
    ["chatglm.cn", "zai"],
    ["www.bigmodel.cn", "zai"],
    ["chatgpt.com", "chatgpt"],
    ["chat.openai.com", "chatgpt"],
    ["example.com", "generic"],
    ["localhost", "generic"],
  ];
  for (const [hostname, expected] of cases) {
    test(`${hostname} -> ${expected}`, () => {
      expect(sites.selectFor(hostname).name).toBe(expected);
    });
  }
});

describe("empty-DOM behavior (never throws)", () => {
  test("site composer on an empty page returns null", () => {
    document.body.innerHTML = "";
    expect(sites.chatgpt.composer()).toBeNull();
  });
  test("generic assistantMessages is always an empty array", () => {
    document.body.innerHTML = "";
    expect(sites.generic.assistantMessages()).toEqual([]);
  });
});
```

- [ ] **Step 3: Run to verify RED**

Run: `npx vitest run`
Expected: FAIL — `sites.selectFor is not a function` (module.exports is undefined so the default import is an empty object).

- [ ] **Step 4: Implement the shim** — in `extension/sites.js`, replace ONLY the tail of the IIFE (currently lines ~234-245):

```js
  function selectFor(hostname) {
    function has(s) {
      return hostname.indexOf(s) !== -1;
    }
    if (has("claude.ai")) return claude;
    if (has("gemini.google.com")) return gemini;
    if (has("grok.com")) return grok;
    if (has("perplexity.ai")) return perplexity;
    if (has("z.ai") || has("chatglm.cn") || has("bigmodel.cn")) return zai;
    if (has("chatgpt.com") || has("openai.com")) return chatgpt;
    return generic;
  }

  // Test-only export shim (Node/vitest). Dead branch in the browser -- Chrome
  // content scripts have no `module`, so this changes nothing at runtime.
  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      chatgpt: chatgpt,
      claude: claude,
      gemini: gemini,
      grok: grok,
      perplexity: perplexity,
      zai: zai,
      generic: generic,
      selectFor: selectFor,
      helpers: {
        visible: visible,
        isTextField: isTextField,
        pickVisible: pickVisible,
        genericComposer: genericComposer,
        readComposer: readComposer,
        writeComposer: writeComposer,
      },
    };
  }

  return selectFor(location.hostname);
})();
```

The old inline `const HOST = location.hostname; function has(s) {...} if (...) return ...;` block is deleted — `selectFor(location.hostname)` reproduces it exactly (same order, same substrings).

- [ ] **Step 5: Run to verify GREEN + browser-path sanity**

Run: `npx vitest run` → all PASS.
Run: `node --check extension/sites.js` → exit 0 (syntax valid for the browser path).

Interop escape hatch: if `import sites from "../sites.js"` yields an empty object under vitest's CJS interop, switch the tests to `import { createRequire } from "node:module"; const require = createRequire(import.meta.url); const sites = require("../sites.js");` (same in Task 2) — do NOT add `"type"` to package.json or convert sites.js to ESM.

- [ ] **Step 6: Commit**

```bash
git add package.json package-lock.json vitest.config.js extension/sites.js extension/tests/sites.routing.test.js .gitignore
git commit -m "test(js): vitest+jsdom harness + sites.js export shim with selectFor routing tests"
```

---

### Task 2: Per-site fixture tests (composer / assistantMessages / read / write)

**Files:**
- Create: `extension/tests/fixtures/chatgpt.html`, `claude.html`, `gemini.html`, `grok.html`, `perplexity.html`, `zai.html`; `extension/tests/sites.dom.test.js`
- Test: itself

**Interfaces:**
- Consumes: Task 1's exports. Fixtures are MINIMAL hand-written DOM matching the selectors in `extension/sites.js` (see the selectors quoted in each fixture below) — not full-page dumps.

- [ ] **Step 1: Write the fixtures** (each file is the full file content):

`extension/tests/fixtures/chatgpt.html` (selectors: `#prompt-textarea`, `[data-message-author-role='assistant']`):

```html
<main>
  <div data-message-author-role="user"><p>คำถามของผู้ใช้</p></div>
  <div data-message-author-role="assistant"><p>คำตอบจากผู้ช่วย [ชื่อ_1]</p></div>
  <form><div id="prompt-textarea" class="ProseMirror" contenteditable="true"><p></p></div></form>
</main>
```

`extension/tests/fixtures/claude.html` (selectors: `div.ProseMirror[contenteditable='true']`, `div.font-claude-response`):

```html
<main>
  <div class="font-claude-response"><p>คำตอบจาก Claude [โทรศัพท์_1]</p></div>
  <fieldset><div class="ProseMirror" contenteditable="true"><p></p></div></fieldset>
</main>
```

`extension/tests/fixtures/gemini.html` (selectors: `rich-textarea div.ql-editor[contenteditable='true']`, `message-content.model-response-text`):

```html
<main>
  <message-content class="model-response-text"><p>คำตอบจาก Gemini</p></message-content>
  <rich-textarea><div class="ql-editor" contenteditable="true"><p></p></div></rich-textarea>
</main>
```

`extension/tests/fixtures/grok.html` (selectors: `textarea`, `.message-bubble`):

```html
<main>
  <div class="message-bubble"><p>คำตอบจาก Grok</p></div>
  <textarea placeholder="Ask Grok anything"></textarea>
</main>
```

`extension/tests/fixtures/perplexity.html` (selectors: `textarea[placeholder]`, `div.prose`):

```html
<main>
  <div class="prose"><p>คำตอบจาก Perplexity</p></div>
  <textarea placeholder="Ask anything..."></textarea>
</main>
```

`extension/tests/fixtures/zai.html` (selectors: `textarea`, `.markdown-body`):

```html
<main>
  <div class="markdown-body"><p>คำตอบจาก GLM</p></div>
  <textarea placeholder="พิมพ์ข้อความ"></textarea>
</main>
```

- [ ] **Step 2: Write the failing tests** — create `extension/tests/sites.dom.test.js`:

```js
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, test } from "vitest";
import sites from "../sites.js";

const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), "fixtures");

function load(name) {
  document.body.innerHTML = readFileSync(join(FIXTURES, `${name}.html`), "utf8");
}

const SITES = ["chatgpt", "claude", "gemini", "grok", "perplexity", "zai"];

describe.each(SITES)("%s fixture", (name) => {
  beforeEach(() => load(name));

  test("composer() finds the input", () => {
    const el = sites[name].composer();
    expect(el).not.toBeNull();
    const editable =
      el.tagName === "TEXTAREA" ||
      el.tagName === "INPUT" ||
      el.getAttribute("contenteditable") === "true";
    expect(editable).toBe(true);
  });

  test("assistantMessages() returns at least one reply node", () => {
    const nodes = sites[name].assistantMessages();
    expect(Array.isArray(nodes)).toBe(true);
    expect(nodes.length).toBeGreaterThan(0);
    expect(nodes[0].textContent).toContain("คำตอบ");
  });

  test("writeComposer/readComposer round-trip", () => {
    const el = sites[name].composer();
    const ok = sites[name].writeComposer(el, "ข้อความทดสอบ [ชื่อ_1]");
    expect(ok).toBe(true);
    expect(sites[name].readComposer(el)).toBe("ข้อความทดสอบ [ชื่อ_1]");
  });
});

describe("cross-fixture safety", () => {
  test("chatgpt selectors do not fire on the claude fixture", () => {
    load("claude");
    expect(sites.chatgpt.assistantMessages()).toEqual([]);
  });
  test("generic composer works on every fixture (drift safety net)", () => {
    for (const name of SITES) {
      load(name);
      expect(sites.generic.composer()).not.toBeNull();
    }
  });
});
```

- [ ] **Step 3: Run to verify state**

Run: `npx vitest run`
Expected: mostly PASS immediately (the code under test already exists — RED here applies only if a fixture/selector mismatch reveals a genuine bug). Investigate ANY failure by comparing the fixture against `extension/sites.js` selectors: fix the FIXTURE if it misrepresents the site markup this extension targets; report (do not "fix") the production selector unless it is provably broken.

- [ ] **Step 4: Commit**

```bash
git add extension/tests/fixtures extension/tests/sites.dom.test.js
git commit -m "test(js): per-site DOM fixtures pinning composer/assistantMessages/write-read paths"
```

---

### Task 3: Rust kill-path tests (shutdown request + tree kill)

**Files:**
- Modify: `desktop/src-tauri/src/sidecar.rs`
- Test: same file (`#[cfg(test)]` modules)

**Interfaces:**
- Produces: `fn shutdown_request(token: Option<&str>) -> String` (the exact bytes written today, extracted); `fn send_shutdown(addr: std::net::SocketAddr, token: Option<&str>)` (the bounded connect/write block, extracted); `pub(crate) fn kill_with(state: &SidecarState, addr: std::net::SocketAddr)` (the whole current `kill` body, parameterized by address); `pub fn kill(app: &AppHandle)` delegates: `kill_with(&app.state::<SidecarState>(), "127.0.0.1:8000".parse().expect("valid socket addr"))`. Behavior byte-identical: same header order, same timeouts, same lock/take order.

- [ ] **Step 1: Extract-function refactor** — in `sidecar.rs`, replace the body of `kill` (lines ~120-162):

```rust
/// The raw HTTP request kill() writes to ask the backend to exit. Kept as a
/// pure function so tests can pin the exact bytes (header order matters to
/// nobody, but presence does: X-AIGuard-Local always, X-AIGuard-Token only
/// when we spawned the sidecar ourselves).
fn shutdown_request(token: Option<&str>) -> String {
    let mut req =
        String::from("POST /api/shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nX-AIGuard-Local: 1\r\n");
    if let Some(tok) = token {
        req.push_str("X-AIGuard-Token: ");
        req.push_str(tok);
        req.push_str("\r\n");
    }
    req.push_str("Content-Length: 0\r\nConnection: close\r\n\r\n");
    req
}

/// Best-effort graceful stop: bounded connect + write of the shutdown request.
fn send_shutdown(addr: std::net::SocketAddr, token: Option<&str>) {
    use std::io::Write;
    if let Ok(mut stream) = std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(500))
    {
        let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
        let _ = stream.write_all(shutdown_request(token).as_bytes());
    }
}

/// Kill sequence, parameterized by backend address so tests can point it at a
/// mock listener: (1) ask the backend to exit, (2) kill the child handle,
/// (3) force-kill the stored PID's process tree (the real guarantee).
pub(crate) fn kill_with(state: &SidecarState, addr: std::net::SocketAddr) {
    let token = state.token.lock().unwrap().clone();
    send_shutdown(addr, token.as_deref());
    let child = state.child.lock().unwrap().take();
    if let Some(child) = child {
        let _ = child.kill();
    }
    let pid = state.pid.lock().unwrap().take();
    if let Some(pid) = pid {
        force_kill_tree(pid);
    }
}

/// Kill the sidecar process tree. Best-effort: graceful shutdown request, then
/// kill the child handle, then force-kill the stored PID's tree to also reap
/// the PyInstaller child.
pub fn kill(app: &AppHandle) {
    let state = app.state::<SidecarState>();
    kill_with(&state, "127.0.0.1:8000".parse().expect("valid socket addr"));
}
```

Keep the existing explanatory comments (bounded-timeout rationale, mutex drop-order note) attached to their new homes; delete nothing semantic. `use std::io::Write;` moves from inside `kill` into `send_shutdown`.

- [ ] **Step 2: Write the failing tests** — append to `sidecar.rs` (note: the existing test module at the top stays; these are new modules at the bottom):

```rust
#[cfg(test)]
mod shutdown_request_tests {
    use super::*;

    #[test]
    fn request_without_token_has_legacy_header_only() {
        let req = shutdown_request(None);
        assert!(req.starts_with("POST /api/shutdown HTTP/1.1\r\n"));
        assert!(req.contains("X-AIGuard-Local: 1\r\n"));
        assert!(!req.contains("X-AIGuard-Token"));
        assert!(req.ends_with("Content-Length: 0\r\nConnection: close\r\n\r\n"));
    }

    #[test]
    fn request_with_token_carries_both_headers() {
        let req = shutdown_request(Some("cafe1234"));
        assert!(req.contains("X-AIGuard-Local: 1\r\n"));
        assert!(req.contains("X-AIGuard-Token: cafe1234\r\n"));
    }

    #[test]
    fn kill_sequence_sends_authenticated_shutdown_to_the_given_addr() {
        use std::io::Read;
        use std::sync::mpsc;

        let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("bind mock backend");
        let addr = listener.local_addr().expect("mock addr");
        let (tx, rx) = mpsc::channel::<String>();
        std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut buf = String::new();
                let _ = stream.read_to_string(&mut buf);
                let _ = tx.send(buf);
            }
        });

        let state = SidecarState::default();
        *state.token.lock().unwrap() = Some("tok123".to_string());
        kill_with(&state, addr);

        let received = rx
            .recv_timeout(std::time::Duration::from_secs(5))
            .expect("mock backend never received the shutdown request");
        assert!(received.contains("POST /api/shutdown"));
        assert!(received.contains("X-AIGuard-Token: tok123"));
        assert!(received.contains("X-AIGuard-Local: 1"));
    }
}

#[cfg(all(test, windows))]
mod kill_tree_tests {
    use super::*;

    #[test]
    fn kill_with_force_kills_the_stored_pid_tree() {
        // Victim: cmd spawns ping as a child -> a real 2-process tree. ping -n 60
        // keeps it alive far longer than the test needs.
        let mut victim = std::process::Command::new("cmd")
            .args(["/C", "ping -n 60 127.0.0.1 > NUL"])
            .spawn()
            .expect("spawn victim tree");
        let pid = victim.id();

        // Unreachable addr: connect_timeout fails fast, proving the kill path
        // does not depend on a live backend.
        let state = SidecarState::default();
        *state.pid.lock().unwrap() = Some(pid);
        kill_with(&state, "127.0.0.1:1".parse().expect("valid socket addr"));

        // The tree must die promptly; poll try_wait up to ~5s.
        let mut dead = false;
        for _ in 0..50 {
            if victim.try_wait().expect("try_wait").is_some() {
                dead = true;
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(100));
        }
        assert!(dead, "victim process tree survived kill_with/taskkill");
    }
}
```

- [ ] **Step 3: RED then GREEN**

RED first: run `cd desktop/src-tauri && cargo test` BEFORE applying Step 1's refactor (tests reference `shutdown_request`/`kill_with` that don't exist → compile error = RED). Then apply Step 1, re-run:
Run: `cd desktop/src-tauri && cargo test`
Expected: all tests pass, including the two pre-existing test modules. If the sidecar placeholder binary is required by build and missing, create it the way `.github/workflows/ci.yml` stages it.

- [ ] **Step 4: Commit**

```bash
git add desktop/src-tauri/src/sidecar.rs
git commit -m "test(rust): pin sidecar kill sequence -- shutdown request bytes, mock-backend delivery, tree kill"
```

---

### Task 4: CI job, docs, PR

**Files:**
- Modify: `.github/workflows/ci.yml`, `docs/superpowers/specs/2026-07-10-post-competition-longterm-roadmap.md`

**Interfaces:** consumes everything above.

- [ ] **Step 1: Add the CI job** — in `.github/workflows/ci.yml`, add alongside the existing jobs (match the file's indentation/style; KEEP the existing `js syntax` job):

```yaml
  js-tests:
    name: js tests (vitest)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: "npm"
      - run: npm ci
      - run: npx vitest run
```

- [ ] **Step 2: Roadmap status line** — append to the "อัปเดตสถานะ (2026-07-16)" section:

```markdown
- **Horizon-2 #13 (แกน test) — เสร็จ (2026-07-17)**: vitest+jsdom harness (sites.js export shim + selectFor; routing/fixture/write-read tests ทั้ง 6 site) + Rust kill-sequence tests (shutdown request bytes, mock-backend delivery, taskkill tree จริง) + CI job `js tests (vitest)` — Playwright live-DOM กับ selector-drift badge เลื่อนไปรอบถัดไปตาม spec
```

- [ ] **Step 3: Full verification**

Run: `npx vitest run` → all pass. `node --check` every extension/*.js and desktop JS file the old CI job covers (same command list as the `js syntax` job). `cd desktop/src-tauri && cargo test` → pass. `git diff main --stat -- '*.py'` → empty (no Python touched).

- [ ] **Step 4: Commit + push + PR**

```bash
git add .github/workflows/ci.yml docs/superpowers/specs/2026-07-10-post-competition-longterm-roadmap.md
git commit -m "ci: vitest job for the JS harness; roadmap status for Horizon-2 #13 core"
git push -u origin feat/js-rust-test-harness
gh pr create --base main --title "test: JS/Rust test harness core (Horizon-2 #13)" --body "..."
```

PR body must contain: (1) scope note — vitest+jsdom + Rust kill tests + CI; Playwright/badge deferred per spec; (2) the additive-shim guarantee (browser path unchanged, node --check green); (3) test inventory (routing 11 cases, 6 fixtures x 3 assertions + 2 safety tests, 4 Rust tests incl. real tree-kill); (4) confirmation no Python files touched. End with the line: 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## Final verification (controller)

- [ ] `git diff main -- tests/test_step11_api.py tests/test_api_hardening.py CLAUDE.md '*.py'` → empty
- [ ] CI green including the new `js tests (vitest)` job and `cargo test` with the new modules
- [ ] Final whole-branch review → merge
