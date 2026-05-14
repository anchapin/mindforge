# Governance

## Project Owner

Alex — owns the project direction, phase scope, and final merge authority.

## Decision Making

Benevolent dictator model. The owner makes final decisions after seeking
community input. Consensus is sought but not required for routine changes.

## Maintainer Criteria

Maintainers are contributors who have:

- Submitted 3+ merged PRs
- Demonstrated understanding of the spec
- Responded to issues within 48h

## RFC Process

For significant architectural changes:

1. Open a GitHub Discussion with the `RFC` label
2. Describe the problem, proposed solution, and alternatives considered
3. Allow 7 days for community feedback
4. Owner makes final decision

## Phase Exit Criteria

Each phase exit (SPEC.md Sections 5.1–5.4) requires:

1. All automated tests passing
2. Manual verification of phase exit criteria
3. Version bump git tag
4. CHANGELOG.md entry

## Skill Marketplace Policy (Phase 4)

Submitted skills must:

- Pass `yaml.safe_load()` validation
- Have no external actions without approval gates
- Include a test case
- Be licensed under AGPL-3.0 or compatible

## Community SLA

| Commitment | Target |
|---|---|
| Issue acknowledgment | Within 48h |
| PR initial review | Within 7 days |
| Bug fix (confirmed) | Within 14 days |
| Security disclosure response | Within 48h |
| Good first issue guidance | Within 7 days |

**Contribution acceptance:** All contributions are welcome. Merging is not
guaranteed — contributions must pass review criteria (CONTRIBUTING.md) and
align with the phase scope. Low-quality PRs (missing tests, no spec update,
breaking changes without disclosure) will be closed with guidance.

**Phase gates:** Phase 4 infrastructure contributions (Composio, full OAuth)
will be accepted as PRs but not merged until Phase 4 begins. Label with
`Phase 4` and `on-hold` to signal this.

## Reporting a Vulnerability

Please report security vulnerabilities via GitHub Issues or directly to the
owner with:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested mitigations

Response timeline: acknowledgment within 48h, fix within 14 days for critical issues.
