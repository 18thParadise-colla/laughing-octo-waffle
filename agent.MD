# Agent Instructions for Python Projects

These guidelines describe how I should work with this repository and your Python code.

## Core principles
- **Clarity first:** favor readable, maintainable code over clever tricks.
- **Small, safe changes:** make focused edits that minimize risk and are easy to review.
- **Consistency:** follow existing project conventions when they exist.

## Python best practices
- **Style & formatting**
  - Follow [PEP 8](https://peps.python.org/pep-0008/) naming and layout.
  - Use 4 spaces for indentation; avoid tabs.
  - Keep line length at or below 88 characters when possible.
  - Prefer f-strings for string interpolation.

- **Typing & interfaces**
  - Add type hints for new or modified functions when practical.
  - Keep public interfaces stable; avoid breaking changes without notice.

- **Error handling**
  - Validate external inputs early.
  - Raise specific exceptions; avoid bare `except`.

- **Dependencies**
  - Prefer standard library modules when they suffice.
  - Avoid adding new dependencies unless clearly justified.

- **Testing**
  - Add or update tests to cover behavioral changes when feasible.
  - Keep tests deterministic and isolated.

- **Security & robustness**
  - Never hardcode secrets.
  - Handle file paths safely and portably.

## Workflow expectations
- **Explain changes:** summarize what changed and why.
- **Cite sources:** reference files and lines in final responses.
- **Run checks:** execute relevant tests or linters if available; report results.
