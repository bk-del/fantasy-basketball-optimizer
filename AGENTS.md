# Repository instructions

Read `fantasy-basketball-optimizer-guides/AGENTS.md` and
`fantasy-basketball-optimizer-guides/STATUS.md` in full before exploring or editing.
The guide's instructions are mandatory. Its relative documentation paths resolve
inside `fantasy-basketball-optimizer-guides/`; build/check commands run here at the
project root. Update that existing STATUS.md as the single handoff document.

Implement only the current authorized stage and stop at its approval gate.

Before editing, create or switch to a `dev_<feature>` branch based on `dev`.
Agent changes enter `dev` through a reviewed, passing pull request. Promote `dev`
to protected `main` only through a separately verified and owner-approved pull
request. Never commit directly to `main` or `dev`, force-push those branches, or
bypass protection. Follow the workflow in the guide's `docs/DESIGN_RULES.md`.
