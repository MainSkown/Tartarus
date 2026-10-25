# C2a-fixes notes (done / running / next)

Baseline before any change: `pytest -q` in cape/ -> 673 passed.

## Done (each test-first: failing run seen, then code)
1. clone.changeable_options removed; Profile.clone_changeable_options() reads option.changeable_on_clone; old key rejected with a pointer to changeable_on_clone.
2. pipeline `when` (Condition: option + value | not); Profile.build_pipeline(kind, option_values), clone_pipeline(option_values); omitted options take defaults; step_names() unchanged.
3. agent.interactive {options, task_fields} replaces agent.interactive_options.
4. hardware.persona (slug, default "default").
5. signal catalog untouched, as instructed.
a. Registry.list() skips unreadable guest.json; Registry.broken() -> [(name, message)].
b. loader checks selftest.sample.source / selftest.facts.script exist inside the profile dir; fixture files in cape/tests/fixtures/profiles/<id>/selftest/.

## Running
- nothing

## Next
- nothing; final run: 718 passed, ruff check clean, format --check clean on touched files.
