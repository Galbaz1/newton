# Security and data boundaries

Newton currently supports local use on a trusted machine. Bind the app and its
services to loopback. It is not ready to expose directly to the internet or a
shared LAN. Shared deployment needs additional identity, recovery, abuse protection,
HTTPS, parsing isolation and tested operational controls.

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

MLflow student/admin roles are application permissions, not shell or host access.
Keep teaching and private profiles separate and reachable only through an approved
encrypted route. Processes under the same OS account are not isolated from each
other's files. The visual encoder is loopback-only and has no application login;
local processes can reach it.

Report suspected vulnerabilities privately to the repository owner through an
existing authorized channel. Share a minimal synthetic reproduction and affected
version; do not post customer data, credentials or private logs in an issue.
