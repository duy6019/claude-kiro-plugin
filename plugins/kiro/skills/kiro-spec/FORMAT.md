# Kiro spec format

Rules for writing a Kiro spec, taken from the prompts bundled in Kiro IDE and from real Kiro specs.
Write specs only, never source code. Read the code the spec touches and cite `path:line` for claims about current
behaviour. Name the spec in kebab-case. EARS keywords (THE, WHEN, IF, THEN, SHALL, SHALL CONTINUE TO), clause
numbering and the required section headings stay English in every language; only free text may be another language.

## Files in `<repo>/.kiro/specs/<name>/`

| File | Notes |
|------|-------|
| `.config.kiro` | `{"specId": "<uuid4>", "workflowType": "requirements-first" or "design-first", "specType": "feature" or "bugfix"}` |
| `requirements.md` (feature) or `bugfix.md` (bugfix) | what, never how |
| `design.md` | how |
| `tasks.md` | checklist Kiro runs ("Start task") |
| `tasks.meta.json` | written by Kiro (execution history). Never create or edit it. |

## requirements.md (feature)

```
# Requirements Document

## Introduction
## Glossary
- **System_Name**: definition
## Requirements
### Requirement 1: <title>
**User Story:** As a <role>, I want <feature>, so that <benefit>
#### Acceptance Criteria
1. WHEN <event>, THE <System_Name> SHALL <response>
```

Every criterion uses exactly one EARS pattern:
- Ubiquitous: `THE <system> SHALL <response>`
- Event: `WHEN <trigger>, THE <system> SHALL <response>`
- State: `WHILE <state>, THE <system> SHALL <response>`
- Unwanted event: `IF <condition>, THEN THE <system> SHALL <response>`
- Optional: `WHERE <option>, THE <system> SHALL <response>`
- Complex: clause order WHERE, WHILE, WHEN/IF, THE, SHALL

Quality rules (INCOSE):
- Active voice; no vague words ("quickly", "adequate", "user-friendly"); no pronouns ("it", "them"); use Glossary terms.
- Measurable and testable; one thought per criterion.
- No escape clauses ("where possible", "if feasible"); no unqualified "never", "always", "100%".
- State what the system does, not how (how goes to design). Prefer SHALL over SHALL NOT, except for error handling.
- Every system name used in a criterion is defined in the Glossary.
- A parser or serializer gets explicit requirements for the grammar, a pretty printer, and a round-trip property (parse, print, parse).

## bugfix.md (bugfix)

Only these sections: `# Bugfix Requirements Document`, `## Introduction`, `## Bug Analysis` with three subsections.
Technical context, file analysis and implementation details belong in `design.md`, not here.

```
### Current Behavior (Defect)
1.1 WHEN <condition> THEN the system <incorrect behavior>
### Expected Behavior (Correct)
2.1 WHEN <condition> THEN the system SHALL <correct behavior>
### Unchanged Behavior (Regression Prevention)
3.1 WHEN <condition> THEN the system SHALL CONTINUE TO <existing behavior>
```

- Clauses are numbered `X.Y` (section, clause).
- Each Current clause has a matching Expected clause for the same condition.

## design.md

Feature (requirements-first): Overview, Architecture (Mermaid diagrams), Components and Interfaces, Data Models, Correctness Properties, Error Handling, Testing Strategy.
- Use real Go code, not pseudocode, because the repos are Go.
- Correctness Properties section: only when property-based tests fit. Skip it for infrastructure wiring, config, simple CRUD, and external-service behaviour; use integration or smoke tests there.
- Each property is `Property N: <title>`, a `_For any_ ...` statement, and `**Validates: Requirements X.Y**`.
- Design-first: write design before requirements, then derive requirements from it, then map properties to requirement clauses.
- Testing Strategy always names the unit tests: which functions, which cases (normal, edge, error).

Bugfix: `# <Name> Bugfix Design`, then in order: Overview, Glossary (Bug_Condition (C), Property (P), Preservation, key functions with file paths), Bug Details (Bug Condition with `isBugCondition` pseudocode, Examples), Expected Behavior (Preservation Requirements), Hypothesized Root Cause, Correctness Properties, Fix Implementation (Changes Required: file, function, specific changes), Testing Strategy.
- Correctness Properties has exactly two: `Property 1: Bug Condition` (validates the 2.x clauses) and `Property 2: Preservation` (validates the 3.x clauses; fixed function equals original for non-bug inputs).
- Testing Strategy: Exploratory Bug Condition Checking (tests that fail on unfixed code), Fix Checking, Preservation Checking, Unit Tests, Property-Based Tests, Integration Tests.

## tasks.md (feature)

```
# Implementation Plan: <Name>

## Overview
## Tasks
- [ ] 1. <task>
  - <detail bullet>
  - _Requirements: 1.1, 1.2_
- [ ] 2. <task>
  - [ ] 2.1 <sub-task>
    - _Requirements: 2.1_
  - [ ] 2.2 Write unit tests for <component>
    - _Requirements: 2.1_
  - [ ]* 2.3 Write property test for <component>
    - **Property 1: <title>**
    - **Validates: Requirements 2.1**
- [ ] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
## Notes
## Task Dependency Graph
```

Rules:
- At most two levels: top-level `1.` and sub-tasks `1.1`. Every item is a checkbox.
- Each task is a discrete coding step that builds on earlier ones. End by wiring everything together; no orphaned code.
- Only coding work: write, modify or test code, create files. Forbidden: user acceptance testing, deployment, performance measurement, running the app by hand, training, docs, business or marketing steps.
- Reference granular clauses (`_Requirements: 2.1, 2.3_`), never only a user story. Every requirement clause is referenced by at least one task.
- Unit tests are required. Every task that adds or changes code has a unit test sub-task (`- [ ] N.M Write unit tests for ...`) right after the code it covers, and it is never marked `*`.
- Tests are sub-tasks of the code they cover, never standalone. Only extra tests (property, fuzz, integration) may be optional `[ ]*`. Only sub-tasks may carry `*`; top-level tasks, core implementation and unit tests never do.
- Property tests: one sub-task per property, placed right after the code it covers, with `**Property N: ...**` and `**Validates: Requirements X.Y**`. Add them only when the design has Correctness Properties.
- Checkpoint tasks at sensible breaks, text exactly `Ensure all tests pass, ask the user if questions arise.`
- Go tests use a `-timeout` of at most 300s. Testcontainers or Docker tests are marked "not verifiable locally (no Docker)".
- The implementation language is Go; never leave it open.

`## Task Dependency Graph` is a fenced `json` block `{"waves": [{"id": 0, "tasks": ["1.1"]}, ...]}`:
- Each incomplete leaf sub-task (decimal id) appears in exactly one wave. Checkpoints and top-level tasks are left out. Optional `*` sub-tasks are included.
- Wave ids are contiguous integers from 0. Wave N runs only after waves 0..N-1 finish; tasks in one wave run in parallel.
- Tasks that write the same file go in different waves. Setup tasks come first; tests come after the code they test.

## tasks.md (bugfix)

Kiro's bugfix workflow uses a fixed order, standalone test tasks, no `*` markers and no dependency graph:

```
# Implementation Plan

- [ ] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - <title>
  - Scoped to the failing cases from isBugCondition; run on UNFIXED code; **EXPECTED OUTCOME**: test FAILS
  - Document the counterexamples found
  - _Requirements: 1.1_
- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - <title>
  - Observe UNFIXED behaviour for non-bug inputs, then encode it; **EXPECTED OUTCOME**: tests PASS
  - _Requirements: 3.1_
- [ ] 3. Fix <bug>
  - [ ] 3.1 <change>
    - _Bug_Condition: isBugCondition(input) from design_
    - _Expected_Behavior: expectedBehavior(result) from design_
    - _Preservation: Preservation Requirements from design_
    - _Requirements: 2.1, 3.1_
  - [ ] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - re-run the SAME test from task 1
  - [ ] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - re-run the SAME tests from task 2
- [ ] 4. Checkpoint - Ensure all tests pass
```

- The `**Property N: ...**` lines drive Kiro's hover status; keep that exact format.
- Tasks 1 and 2 are top-level and required, never sub-tasks.

## Do not

- Do not fill requirements with guesses. List unknowns as open questions at the end of the file.
- Do not use change-history phrasing ("now", "no longer") in the documents.
- Do not create `tasks.meta.json`.
