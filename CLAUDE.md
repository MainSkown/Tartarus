# Development rules

Three rules govern how code is written in this repo. They apply to the backend (Python/FastAPI)
and the frontend (Vue/Quasar) equally. Specs live in [docs/](docs/); this file is about *how* to
write the code that implements them, not *what* to build.

## 1. Code is self-documenting — comment sparingly

The code should read clearly enough that a comment restating it is unnecessary. Reach for naming,
small functions and clear structure before reaching for a comment.

- **Names carry meaning.** `queue_runner.next_eligible_analysis()`, not `get_next()` with a
  comment above it saying what it does.
- **Functions do one thing** and are named after that thing. If you need a comment to explain
  what a block in the middle of a function does, that block is probably a function that should
  be extracted.
- **Comment the *why*, never the *what*.** A comment is justified when the code can't say it:
  a workaround for a CAPE quirk, a non-obvious ordering requirement, a deliberately-skipped
  edge case, a reference to the spec section or CAPE source line that explains a magic value.
  ```python
  # bad
  # increment retry count
  retries += 1

  # ok — explains a non-obvious constraint the code itself can't express
  # CAPE's ResultServer writes BSON records non-atomically; a partial record at EOF
  # is normal mid-write, not corruption. Wait for more bytes instead of raising.
  if not record.is_complete():
      return
  ```
- **Docstrings are for public API boundaries**, not every function: FastAPI route handlers (used
  for the generated OpenAPI description), the normaliser interface each source implements, the
  Sigma pipeline, exported Vue composables. A private helper two lines long needs no docstring.
- **Type hints and Pydantic/TypeScript types replace a lot of comments.** Prefer a precise type
  over a comment describing the shape of a value.
- **Delete commented-out code.** Git has the history.

## 2. Test-first — the test exists before the code that passes it

Write the test, watch it fail, then write the minimum code to pass it, then refactor.

- **A unit of behavior gets a test before it gets an implementation.** This applies to a new
  endpoint, a normaliser mapping, a query-grammar rule, a Sigma condition, a Vue composable, a
  Pinia store action — not to throwaway exploration, but anything that ends up in a commit does.
- **Write the test against the interface you wish you had**, not the one that's easiest to
  implement. If the test is awkward to write, that's signal to change the design before writing
  the implementation, not after.
- **Pick the cheapest test that would actually fail if the code were wrong.** Don't reach for an
  integration test (OpenSearch/Postgres testcontainers, a CAPE fixture replay) when a pure
  function test on a normaliser or the query compiler proves the same thing faster.
  - Backend: `pytest`. Pure logic (normalisers, query grammar, Sigma matcher) as unit tests
    with fixtures, no containers. Anything touching OpenSearch/Postgres through testcontainers.
    The collector against a fixture analysis directory written incrementally, to simulate a
    live run (see [backend spec](docs/specs/backend.md#testing)).
  - Frontend: `vitest` for stores and composables, `@vue/test-utils` for components,
    `playwright` for the handful of flows that must work end to end (submit → live → final).
- **A bug fix starts with a regression test** that reproduces it and fails, then the fix.
- **Coverage is a smell detector, not a target.** A gap in coverage on logic (not on generated
  code, templates, or trivial getters) means a missing test, not a number to chase.

## 3. Modularity — no duplication, one place per responsibility

If you're about to write logic that already exists elsewhere, extend or call that, don't copy it.

- **One normaliser interface, one implementation per source.** Capemon, Sysmon, ETW, Suricata
  and Volatility3 mappers all implement the same `Normalizer` protocol (see
  [data-model](docs/specs/data-model.md)); shared logic (derived-event emission, ECS field
  helpers, severity mapping) lives in one place they all call, not copy-pasted into each.
- **Shared Vue pieces are components or composables, not copy-pasted templates.** The severity
  badge, lane icon, query bar, and the "filter on / filter out" action used across Events,
  Network, Artifacts and the detail drawer are each written once
  ([gui spec](docs/specs/gui.md#frontend-structure)).
  - If the same markup or logic appears in two places, extract it before the third copy.
- **One source of truth per concept.** The field catalog behind the query compiler, the
  autocomplete endpoint, and the Sigma ECS pipeline all read the same field-definition table —
  don't define the field list twice.
- **Reuse CAPE's own code where it already solves the problem** (e.g. the BSON log format),
  rather than re-implementing it from scratch. Reuse the generated API client
  (`@hey-api/openapi-ts`) rather than hand-writing fetch calls.
- **A third occurrence is the trigger to extract**, not the second — don't over-abstract one or
  two similar-looking pieces of code into a premature shared helper before the shape is clear.

## 4. Frontend visual review — screenshot, publish, address comments

A visual screen or component in the frontend (`frontend/`) is not done when the code compiles —
it's done when the actual rendered result has been reviewed and approved. This applies to a new
screen, a new component, and any change that affects layout, spacing, color or interaction
states, not to a pure logic change with no visual effect.

1. **Build it for real first.** Implement the screen or component in Vue/Quasar against the
   [design system](docs/design/design-system.md), no separate mockup step.
2. **Run it and capture it.** Launch the dev server and screenshot every state the change
   touches: default, hover/focus if relevant, loading, empty, and error — not just the happy
   path (see "States and feedback" in the [GUI spec](docs/specs/gui.md)). Also capture any
   state likely to break layout: long filenames and paths, many tags, a wide process tree, a
   narrow window — the GUI has no fixed-width assumptions to lean on.
3. **Check the screenshots yourself before publishing them.** Overflow, clipped text, broken
   wrapping, collisions and misaligned borders are implementation bugs, not review feedback —
   catch and fix them first, so the user is reviewing the design, not finding your layout bugs.
4. **Publish the screenshots as one Artifact**, one page per round, each screenshot labelled
   with its state and route (e.g. "Dashboard — empty state", "Submit dialog — validation
   error"). Tell the user it's ready for review instead of declaring the piece finished.
5. **Wait for and address comments** left directly on the Artifact. Read every comment before
   continuing. For each one: fix the code, re-screenshot the affected state, and republish to
   the same Artifact URL (not a new one) so the comment thread and the images stay linked.
6. **A piece counts as approved** once the user says so, or once a round of republishing draws
   no new comments. Only then move on to the next screen or component.

Don't batch unrelated screens into one review round — one Artifact per screen or component
keeps comments anchored to what they're actually about.

## 5. Delegate by difficulty — match the model to the task

When planning a feature's implementation, split it into subtasks along the module boundaries
rule 3 already defines (one normaliser, one endpoint, one component), rate each subtask's
difficulty, and hand it to a subagent at the cheapest model tier that can do it well. Launch
independent subtasks together, in one message, rather than one at a time.

| Tier | Model | What goes here |
|---|---|---|
| Easy / medium | Haiku | Well-specified, low-ambiguity work with a clear template to follow: a single normaliser mapping already spelled out in [data-model](docs/specs/data-model.md), a CRUD endpoint, a Pydantic/TypeScript model, a Vue component that follows an existing pattern in the [design system](docs/design/design-system.md), writing tests for already-specified behavior, config and doc edits, mechanical refactors. |
| Standard / hard | Sonnet | Most feature work: the query compiler, the Sigma matcher, the collector, the process graph and timeline components, most backend endpoints and Vue pages, non-trivial bug fixes, anything that requires judgment calls within an already-decided design. |
| Extreme | Opus | Real ambiguity, cross-cutting impact, or a high cost if subtly wrong: the M0 container spike, the guest network isolation and iptables rules, designing a new core abstraction (the normaliser protocol, the query grammar), resolving an open question from [tartarus-v1](docs/features/tartarus-v1.md), or anything touching several modules at once. |

- **When difficulty is unclear, round up a tier.** A cheap model producing subtly wrong
  isolation or data-model code costs more to find later than the saved cost now.
- **Rules 1–4 still apply no matter which model writes the code.** A Haiku-written module is
  still test-first, still self-documenting, still reviewed in the frontend screenshot loop if
  it's visual. The model tier changes who writes the first draft, not the bar it has to clear.
- **Give each subagent only the spec sections its subtask needs**, not the whole docs tree —
  this keeps it focused and is a direct consequence of module boundaries already being clean
  (rule 3): a subtask that needs five unrelated spec sections to make sense is probably not cut
  along the right lines.

## Enforcement

- **Backend:** `ruff` (lint + format), `mypy` on `app/`, `pytest --cov=app` in CI. Ruff's
  complexity and duplicate-code-adjacent lints (e.g. `PLR0912`, `C901`) are on.
- **Frontend:** `eslint` + `vue-tsc`, `vitest --coverage`.
- **Pre-commit:** ruff, eslint and the fast unit-test suites run on changed files before commit.
- **CI gate:** no merge with failing tests or lint. A PR that adds code without a preceding test
  commit (or in the same commit, test-then-implementation visible in the diff) gets flagged in
  review.
