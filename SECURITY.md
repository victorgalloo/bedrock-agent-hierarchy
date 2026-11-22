# Security policy

## Supported versions

The project is early; only the latest `main` receives fixes.

## Reporting a vulnerability

Please **do not open a public issue**. Use
[GitHub private vulnerability reporting](https://github.com/victorgalloo/bedrock-agent-hierarchy/security/advisories/new).
Expect an acknowledgement within 5 business days.

## Scope notes

- This library never stores credentials. Bedrock access uses the standard AWS credential chain
  (environment, profile or role); never commit keys, account IDs or endpoints.
- `ChangeManager` only edits files under the `root` you give it and rejects paths outside it.
