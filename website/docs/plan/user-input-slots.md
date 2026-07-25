---
title: User Input Slots
description: Represent fields that cannot be filled from defaults, context, or producer tools.
---

# User Input Slots

User input slots are structured requests for missing values. They allow a
product UI to pause, ask the user for a field, and resume execution without
guessing.

## Slot Sources

- required request fields
- enum fields without mappings
- dynamic option fields
- context fields without defaults
- ambiguous producer outputs

## Adapter Role

The engine should emit slots. The product adapter should decide how to show
forms, popups, default values, and resume UX.

## Related Pages

- [Plan Synthesis](./plan-synthesis.md)
- [Failure Taxonomy](./failure-taxonomy.md)
