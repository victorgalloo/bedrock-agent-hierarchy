# Contributing

Thanks for helping. This project is early; small, focused pull requests are easiest to review.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Python >= 3.11
pip install -e ".[dev]"
ruff check . && ruff format --check . && pytest
```

## Rules

- One logical change per pull request. Add or update a test that fails without your change.
- Unit tests never call the network: use `FakeModel` or a stub client.
- Keep the design rules in the README; if a change breaks one, explain why in the PR.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat(changes): ...`).
- No real company, customer or person data, endpoints, account IDs or secrets in code, fixtures or
  examples. Use fictional areas like `docs`, `triage`, `release`.
- AI-assisted contributions are welcome; say so in the PR (e.g. an `Assisted-by:` trailer) and
  make sure you have reviewed and can explain every line.

By contributing you agree your work is licensed under Apache-2.0 and that you follow the
[Code of conduct](CODE_OF_CONDUCT.md).
