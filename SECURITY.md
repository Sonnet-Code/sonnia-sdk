# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub: open the **Security** tab of this repository and choose **Report a vulnerability**. Do not open a public issue.

Include what you found, how to reproduce it and what an attacker could do with it. We will acknowledge the report as soon as we can and keep you updated until it is fixed.

## Scope

Things we care about in particular:

- Leaking API keys or other secrets (logs, the local control panel, the WebSocket).
- The local control panel or the WebSocket being reachable from other machines without the user asking for it.
- Camera frames or audio being stored or sent anywhere they should not be.
- Prompt injection that makes the assistant run actions it should not.

## Supported versions

Only the latest commit on `main` is supported.
