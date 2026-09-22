# Onboard a company

Newton supports a local account, company onboarding, source preparation and
evidence-backed investigations. You can enter company, machine and source details
manually or use Autonomous onboarding. Each company belongs to one local account;
shared accounts and invitations are outside the current application.

## Add company and machine context

Start with a company name, an optional website and source files. Autonomous
onboarding researches public company information, profiles uploaded material and
prepares source-backed installation candidates. Public research is context, not
proof of ownership or installed-machine identity.

For manual entry, add a machine with its manufacturer, model, location or function,
and known operating conditions. These fields are user-provided descriptions.
Select the machine before uploading a source or asking a question.

Manual upload accepts PDF, UTF-8 TXT/MD, PNG/JPEG/WebP and UTF-8 CSV files up to
25 MiB. Autonomous intake accepts files up to 64 MiB, multiple files, supported
CSV delimiters and annotation JSON. Newton does not crawl websites, synchronize
cloud drives or connect to CMMS or PLC systems. Preserve an original and record
the transformation when you convert an unsupported file.

## Source states

| State | Meaning and next action |
| --- | --- |
| Missing capability | Upload a relevant original. Newton does not add sample data. |
| Missing input: mapping | Select CSV timestamp, value and unit fields. Keep an unknown timezone as source-local time. |
| Quarantined | Inspect the original and resolve the uncertain interpretation before using it. |
| No extracted text | Inspect the original pages or configure visual retrieval. |
| Error on a retained source | Read the error, correct the mapping or upload corrected bytes. The original remains available. |
| Ready | The source supports the named evidence capability. |

CSV selectors expose up to 100 headers. The preview contains the first five rows
and 20 columns, while mappings may select any supported column. Newton preserves
source values and blocks a series with an invalid row. Mapping and correction
records remain available in the source inspector.

Readiness comes from stored source states and configuration. Provider and retrieval
availability are checked when used. Original measurements provide original plots and
per-channel or per-period summaries; they do not enable forecasting or alarms.

## Correct context

An invalid mapping field returns a validation error without changing source version.
A structurally valid mapping that cannot interpret the original data is saved with
an error state. Correct the mapping and save it again; the selected columns and
unit remain visible.

Use source-local time when a timestamp has no confirmed timezone. Add `UTC` only
when the source timestamps are UTC. Source revisions, mappings and machine context
can be corrected. Earlier answers retain their evidence and are marked superseded.

Rejected uploads create no source. After a network error, refresh the source list
and check filename, hash and state before uploading again. The onboarding worker
has explicit pause and resume actions. It does not replay paid requests or crawl
in the background.

## Verify a local journey

A usable local journey lets the intended account select its company and machine,
inspect a supplied source, resolve required mappings, ask a question with a
configured provider, open cited evidence, and correct a source or assumption.
Other accounts must not access those resources.

Synthetic tests and browser receipts cover this local flow. They do not establish
company approval of sources, equipment applicability or independent use by a
student. Setup and new connectors need developer or operator work. See
[setup](../README.md) and [development](development.md).
