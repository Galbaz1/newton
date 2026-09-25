# Security and data boundaries

The documented installation is for local use on a trusted machine. Bind the app
and its services to loopback. Do not expose that installation directly to the
internet or a shared LAN. Shared deployment requires HTTPS, secure cookies,
login abuse protection, account recovery, parsing isolation and tested backups.

- Every company is owned by an application account. Source, machine, conversation
  and onboarding access is checked against that ownership; database RLS and shared
  company membership are not implemented.
- Exact originals and run history live in private storage outside source control.
  Synthetic/demo data is labelled separately. A `.gitignore` is not a substitute
  for checking a proposed commit's contents.
- Provider calls can transfer company context, questions and selected evidence.
  Review provider access and data terms before processing sensitive material.
- No machine-control actions are implemented. Retrieved guidance is not a certified
  diagnosis or an authorization to operate equipment.
- Optional encoder/MLflow access is configured by your operator. This repository
  contains no grants, accounts or routes to a project owner's infrastructure.

Processes under the same OS account can read each other's files. The optional
visual encoder has no application login and must remain on loopback; local
processes can reach it.

Report suspected vulnerabilities through
[GitHub private vulnerability reporting](https://github.com/Galbaz1/newton/security/advisories/new).
If that route is unavailable, email
[fausto@stepintoliquid.nl](mailto:fausto@stepintoliquid.nl) with “Newton security”
in the subject. Include the affected version or commit, the impact and a minimal
synthetic reproduction when possible. Do not post exploit details, customer data,
credentials or private logs in an issue or pull request.
