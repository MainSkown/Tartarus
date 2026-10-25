# The rules

The repo's coding rules are in [.claude/CLAUDE.md](../../.claude/CLAUDE.md). They were written for
the maintainer's AI-assisted workflow, but they apply to every change, backend and frontend alike.
This page is the plain version. The file is the source.

## 1. The code explains itself

Pick names and small functions before a comment. `next_eligible_analysis()` says more than
`get_next()` with a comment above it.

- Comment the *why*: a workaround for a CAPE quirk, an ordering the code cannot express, a magic
  value with its spec section. Do not comment the *what*.
- Use type hints and the Pydantic or TypeScript types instead of a comment about a value's shape.
- Write docstrings for public boundaries: route handlers (they become the OpenAPI description), the
  normaliser interface, the Sigma pipeline and exported composables. A two-line private helper needs none.
- Delete commented-out code. Git keeps the history.

## 2. Test first

Write the test, see it fail, write the least code that passes it, then tidy up.

- A behaviour gets its test before its implementation: an endpoint, a normaliser mapping, a query
  rule, a Sigma condition, a composable, a store action.
- Write the test against the interface you want, not the easiest one to build. A hard-to-write test
  is a sign the design is wrong.
- Pick the cheapest test that would fail if the code were wrong. A pure function test beats an
  integration test that starts containers. [Running the tests](running-the-tests.md) lists the layers.
- A bug fix starts with a regression test that fails before the fix.
- Coverage is a smell detector, not a target.

The CI gate is no merge with failing tests or lint. A pull request that adds code without a test
commit before it, or without a test in the same diff, gets flagged in review.

## 3. No duplication

- One normaliser interface, one implementation per source. Shared logic (ECS helpers, severity,
  derived events) lives in one place that every normaliser calls. See [adding an event source](adding-an-event-source.md).
- Shared Vue pieces are components or composables. If the same markup or logic appears in two places,
  extract it before the third copy.
- One field definition table feeds the query compiler, the autocomplete and the Sigma pipeline.
- Reuse CAPE's own code where it solves the problem, such as the BSON log format. Reuse the generated
  API client rather than writing `fetch` calls by hand.
- A third occurrence is the trigger to extract, not the second.

## 4. Look at the frontend before you call it done

A screen or component is done when its rendered result has been looked at, not when it compiles.
This covers new screens, new components and any change to layout, spacing, colour or interaction.

1. Build it in Vue and Quasar against the [design system](../design/design-system.md).
2. Run it and capture every state it touches: default, hover and focus, loading, empty and error. Also
   capture what breaks layouts: long file names and paths, many tags, a wide process tree, a narrow window.
   `make screenshots` produces the captures (see [running the tests](running-the-tests.md)).
3. Check the captures yourself. Overflow, clipped text and misaligned borders are bugs to fix before review.
4. Include the screenshots, labelled by state and route, in the pull request.

The [GUI spec](../specs/gui.md#states-and-feedback-applies-everywhere) lists the states each screen needs.

## 5. Delegating by difficulty (optional)

This rule is for AI-assisted work. A human contributor can skip it. The idea: split a feature along
the module boundaries from rule 3, give each part to the cheapest tool that can do it well, and read
every diff before it is committed. Rules 1 to 4 apply to the code whoever wrote it.

## Before you open a pull request

- `make lint` and `make test` pass.
- Each new behaviour has a test, and the test fails without the change.
- The frontend change has screenshots of the states it touches.
- The comments say why, not what.
