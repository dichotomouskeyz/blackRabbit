# Data handling and compliance

blackRabbit is research software published under the MIT license. It is
provided as is, without warranty, and it is not certified, validated or
audited for HIPAA, GDPR, 21 CFR Part 11 or any other regulatory regime.
Whether those rules apply, and how to meet them, is the responsibility of the
lab, institution or sponsor that deploys it. This document describes what the
software stores so a deploying team can make that assessment. It is not legal
advice.

## What blackRabbit stores

- **Sessions:** a random session UUID, a pseudonymous participant UUID, site
  and sponsor UUIDs, compound and dose, protocol arm, room, capture source,
  status, and creation, start and close times.
- **Physiology:** EEG, interbeat intervals, electrodermal activity and
  respiration samples with LSL and database timestamps, in TimescaleDB and in
  XDF files on local disk.
- **Context:** ECHO zone and marker events with their labels and timestamps.
- **Analysis:** ARC baselines, response windows, statistics and JSON artifacts
  derived from the above.
- **Audit:** an append-only log of inserts and changes, written by database
  triggers.
- **Logs:** structured process logs that include session and participant
  UUIDs.

## What it does not collect

There are no fields for names, dates of birth, contact details, addresses,
medical record numbers or other direct identifiers. `participant_id` must be a
UUID: the database column is typed `UUID`, session initialization and the API
reject anything else, and the operator console generates one on request.

Keep the key that links a participant UUID to a real person outside
blackRabbit, in the lab's own enrollment or consent record, under that
system's access controls.

## Where identifying information can still appear

Pseudonymous IDs reduce risk but do not by themselves make a dataset
de-identified. A deploying team should account for:

- **Dates and times.** Session and sample timestamps are tied to an
  individual's health data. Under the HIPAA Safe Harbor method, dates more
  specific than the year count as identifiers.
- **Free-text fields.** `therapist_id`, `protocol_arm`, `room_id` and ECHO
  zone and marker labels accept text. Use codes, not names.
- **The physiological signals themselves**, which some frameworks treat as
  biometric or sensitive data.
- **The re-identification key** held by the lab.
- **The optional recording investigator.** When `INVESTIGATION_MODEL` is set
  to an OpenAI or Anthropic model, cited evidence and signal windows are sent
  to that provider. Do not enable it for regulated data without an agreement
  with the provider that covers this use. The scripted demonstration sends
  nothing.
- **The operator console's agent**, which sends operator messages and tool
  results to the model at `AGENT_BASE_URL`. The route refuses anything other
  than a loopback or private-network address.

## What the deploying team is responsible for

- Deciding which regulations and approvals apply (for example HIPAA status and
  business associate agreements, GDPR roles, IRB or ethics approval, consent
  language).
- Access control. The operator API has no authentication and must stay bound
  to localhost; tenant scoping is not user authorization.
- Encryption at rest and in transit, including database storage, XDF files,
  backups and any copies of exports.
- Retention, backup and destruction schedules.
- Participant withdrawal. Permanent removal of a participant's data is not
  implemented and must follow the team's own procedure.
- Validation, audit-trail review and electronic signature controls if records
  will support a regulated submission.
- Breach detection and response.

## Reporting problems

Report data-handling or security issues privately through the repository's
GitHub security advisories rather than a public issue.
