# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.4.x   | :white_check_mark: |
| < 0.4   | :x:                |

## Reporting a Vulnerability

Please report security vulnerabilities to the project maintainer with:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested mitigations

Response timeline: acknowledgment within 48h, fix within 14 days for critical issues.

## Security Model

MindForge is a single-user self-hosted system. The security boundary is the
local machine and the OS user account running the containers. Assume that any
process running under the same user account has full access to all credentials
and data.

Key security boundaries:
- Fernet encryption key (`.env`) — protects sensitive fields at rest in PGLite
- HMAC signatures on semantic memory writes — prevent injection attacks
- `yaml.safe_load()` on all skill YAML — prevents RCE via deserialization
- No exposure of the API server outside localhost
