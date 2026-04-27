# Builder Journal

## 2026-04-25 - Legion repair pass

- Restored a polluted git index with `git restore --staged -- .` instead of destructive checkout/reset.
- `stack-verify.sh detect` can fail accidentally when its final optional detector condition is false; detector commands need explicit success returns after normal completion.
- Hook feedback must not rely on PID-specific async temp files. Synchronous failure output is safer for short hook checks, and nonzero verifier exits need a fallback message even when the verifier does not emit `FAIL|`.
- Settings merge code must handle both invalid JSON and valid JSON with malformed nested structures; validate nested lists before iteration.
- Single-quoted heredocs do not interpolate shell variables. Critical runtime paths should be passed through the environment and have explicit Python fallbacks.

## 2026-04-25 - Legion bootstrap shortcuts

- `legion 0` must not depend on a fully expanded global `$HOME/.claude/scripts`; resolve the local repo script first, then fall back to global install.
- Project initialization scripts need noninteractive mode for one-command bootstraps. A warning about missing `.git` is enough; blocking prompts break automation.
- Shell directory copies are platform-sensitive: on macOS, copying `source/` can copy contents instead of the directory. Copy the directory path itself when preserving skill folder names.
- `legion h` is the ergonomic entrypoint: ensure project initialization, then convene host plus Claude/Codex branch commanders.

## 2026-04-25 - Bare legion command installer

- Do not install `legion` into PATH as a symlink to `~/.claude/scripts/legion`: the shim resolves `BASH_SOURCE[0]` from the symlink directory and looks for the wrong `legion.sh`.
- Install a tiny wrapper script instead: `exec "$HOME/.claude/scripts/legion" "$@"`.
- `legion 0` and `legion h` should both self-heal the global entrypoint before doing project work, because users naturally expect `h` to be the only daily command.
- Daily `legion h` must not recursively scan/copy every skill. Use a lightweight content fingerprint for critical launcher files, and reserve full refresh for `legion 0`.

## 2026-04-25 - Visible host launch

- Users interpret "launched" as "I can see it". Detached tmux sessions are technically running but fail the user expectation.
- `legion h` should attach to the host session by default in an interactive terminal; keep `--no-attach` for scripts.
- Do not pipe interactive Claude Code through `tee`: it loses TTY semantics and can fail with "Input must be provided..." Keep interactive Claude output in the tmux pane.
- When reusing branch commanders, prefer live tmux-backed commanders over stale planned records. Otherwise repeated `h` calls multiply L2 sessions.

## 2026-04-25 - Commander startup context

- Launching a commander is not enough; the first prompt must force context loading before task intake.
- L1 startup needs a broad read: protocol files, skill inventory, historical tactics, mixed status, inbox, and recent events.
- L2 startup needs role filtering: branch/provider-specific skills and tactics, parent/peer commanders, inbox, and readiness report back to the parent.
- For Codex, combine the system prompt and startup self-check into the initial prompt argument. For Claude, pass the startup self-check as the first user prompt while keeping the commander prompt as appended system context.

## 2026-04-25 - L1/L2 readiness handshake

- `--l2-only` broadcast is too broad in a dirty registry; parent-scoped broadcast is required so a host only talks to direct L2 commanders.
- L1 should not hand-roll `sleep`/`grep` loops inside an interactive agent. Put waiting semantics into `legion mixed readiness --wait` so the host has one deterministic command.
- Readiness needs an explicit machine-checkable tag. Use `READY:init-complete` in every L2 startup report and treat `Missing: (none)` as the release gate for user-facing "军团体系展开初始化完成".

## 2026-04-25 - Interactive tmux view

- A read-only `capture-pane` dashboard is not equivalent to Claude Team tmux. The user expects pane-level interaction with the real L1/L2 terminals.
- Use a wrapper tmux session whose panes run `TMUX= tmux attach -t <target-session>`; this preserves each commander's real TTY while giving one split workspace.
- Auto-select must prefer the newest live L1 with live direct L2 commanders. Dirty registries can contain stale test commanders, so never infer L2 globally without parent filtering.

## 2026-04-25 - Dynamic L2 retirement

- Do not retire L2 purely because a task reached terminal state; the real decision is whether the L2's accumulated context is still valuable.
- Campaign L2 can auto-disband after all owned tasks complete when no retention is requested. Host L2 must stay resident.
- Failed or blocked work should retain context by default for diagnosis. Use `retain_context: true` or `context_policy: retain` for expected follow-up even after success; use discard/release policies only when the context is definitely disposable.

## 2026-04-25 - Scale-first doctrine

- Legion's differentiator is not cost minimization; it is maximum effective collaboration scale for better speed and quality.
- Resource cost is not a valid reason to skip corps, recon, review, verify, audit, or parallel workers. Only safety/ambiguity/shared-state/high-rework exceptions can stop flow.
- "Maximum scale" must still be effective: split by file scope, risk hypothesis, verification method, or specialty. Duplicate theater is waste, not scale.

## 2026-04-25 - Default L1/L2 task view

- `legion h` should enter the split view, not the solo L1 session, because initialization is only useful if the user can see the base L2 commanders immediately.
- The default workspace should show base host L2 plus L2 commanders that currently own non-terminal tasks. Retained-but-idle campaign L2 preserve context in the registry/tmux, but should not crowd the default command surface.

## 2026-04-25 - Noninvasive L1 reports

- Do not inject L2-to-L1 reports into the host's interactive prompt with `tmux send-keys`; Claude Code can leave long multi-line reports as unsent composer text after initialization is already complete.
- Keep commander reports durable in mixed inbox and use tmux `display-message` as a non-invasive notification. Reserve `send-keys` for L1-to-L2 directives where active prompting is intentional.
- L1-to-L2 broadcast has the same composer contamination problem. Treat all commander-to-commander mixed messages as inbox records plus tmux notifications; do not inject text into any interactive commander prompt by default.

## 2026-04-25 - Fixed war-room proportions

- Do not call `tmux select-layout` after setting explicit pane sizes; it overwrites the intended proportions.
- Default host view should make L1 the left 40% and L2 the right 60%. Split the right column progressively with `-p 75/67/50...` so all visible L2 panes end up equal height.

## 2026-04-25 - RoundTable skill audit

- `claw-roundtable-skill` is installed in project and global `.claude/skills`, and its demand analysis/expert matching works when the skill directory is on `PYTHONPATH`.
- Full RoundTable execution depends on `openclaw.tools.sessions_spawn`. If that runtime is missing, the skill must fail fast instead of reporting completion with all experts failed.
- RoundTable is now integrated as a shared L1/L2 weapon: every L2 branch prompt runs base health during startup, readiness reports include roundtable health, reused branch commanders refresh prompt artifacts, and Codex can discover it through `.agents/skills/claw-roundtable-skill`.
- No standalone `qiushi`/`求是` `SKILL.md` exists in the current project/global skill roots. The only Qiushi hit is historical Claude project memory, which Legion startup does not load as an executable skill.
