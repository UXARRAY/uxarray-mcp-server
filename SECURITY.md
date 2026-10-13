# Security Model

uxarray-mcp has two security boundaries that behave very differently. Read
the section that applies to you **before** you connect anything.

| If you are … | Read |
|---|---|
| Running locally only | [Local](#local-only) |
| Connecting to an HPC endpoint someone else operates | [Remote — as a user](#remote--as-a-user) |
| Standing up an endpoint for yourself or others | [Remote — as an operator](#remote--as-an-operator) |

---

## Local-only

When uxarray-mcp runs as a subprocess of your AI client on your laptop:

- It can read any file your user account can read.
- It writes plots and outputs to wherever the AI tells it.
- It does not open network listeners. It speaks stdio to the AI client only.

**Risks:**
- The AI may open a file you didn't intend (typo'd path, similar variable name).
- The AI may write outputs that overwrite existing files.
- A malicious MCP client could in principle ask uxarray-mcp to read sensitive
  files — but the same client could read those files directly. The threat
  model here is "trust your MCP client."

**Mitigations:**
- Use AI clients with per-tool-call approval (Claude Code supports this).
- Don't run uxarray-mcp from a sensitive working directory unless needed.

---

## Remote — as a user

**The core fact:** A Globus Compute endpoint executes **arbitrary Python as
the endpoint operator's user account**. When you submit a function, you are
running code on someone else's server. The operator can:

- See every file path and argument you submit.
- Log, modify, or replace the code that runs — and silently return wrong results.
- Read anything the configured user can read (their `$HOME`, their group's data).

This is true of *all* Globus Compute endpoints, not just uxarray-mcp's. The
MCP layer adds no extra protection.

**Before you connect:**

1. **Verify the operator.** Personally or institutionally. "A colleague gave
   me a UUID in Slack" is not enough.
2. **Never paste secrets into prompts** that ship to a remote endpoint —
   tokens, passwords, unredacted personal data, NDA'd dataset contents.
3. **Treat outputs as untrusted** until you've spot-checked them against a
   known reference.
4. **Prefer endpoints your own institution operates** over endpoints from
   unknown third parties.

**What we recommend you ask the operator:**

- Is this a Multi-User Endpoint with a function allowlist? (If yes, blast
  radius is much smaller — only pre-registered functions run.)
- What user account does the endpoint run as? (Service account = safer than
  a personal account.)
- Is high-assurance auth (recent MFA) required? (If yes, a stolen token
  alone can't submit.)

If the operator can't answer these, treat the endpoint as high-risk.

---

## Remote — as an operator

If you are standing up an endpoint on your HPC account, you are giving
**shell-equivalent access to the endpoint's configured user** to anyone who
can submit functions to it.

### What's at stake

A 4-line malicious payload can walk away with everything the endpoint user
can read. Concretely (verified against a real NCAR endpoint, 2026-06-08):

- **`~/.ssh/*`** — private keys, `known_hosts`, `authorized_keys`. Lateral
  movement to every system you SSH into, including GitHub.
- **`~/.globus_compute/credentials/storage.db`** — refresh token.
  **Endpoint takeover that survives UUID rotation.** Re-registering the
  endpoint does NOT invalidate this token; only an explicit Globus re-auth does.
- **`~/.bash_history`** — every command you've typed, including pasted
  tokens, host lists, and one-off `export AWS_…=` lines.
- **`~/.netrc`, `~/.aws/credentials`, `~/.kube/config`** — exfiltrate
  anything you've authenticated against.
- **Group-readable scientific data** — silently modify shared archives;
  downstream papers cite poisoned data.
- **Your HPC allocation** — crypto miners, runaway jobs, exfiltration via
  outbound HTTPS (allowed by default on most login nodes).

### Hardening — minimum (do today)

```bash
chmod 700 ~/.globus_compute ~/.globus
chmod 600 ~/.bash_history
# In endpoint config worker_init, add:
#   unset PYTHONPATH
# (Avoids pydantic/dill conflicts and prevents inherited path injection.)
```

Audit who's authorized:

```bash
globus-compute-endpoint configure-tutorial   # if applicable
# Review .globus_compute/<endpoint-name>/config.yaml for allowed_identities
```

### Hardening — recommended (do this month)

1. **Run as a service account, not your personal user.**
   Request from your HPC site (e.g., `svc_uxarray` at LCRC/NCAR). The
   service account should have:
   - No SSH keys, no `.netrc`, no cloud creds.
   - Read-only ACLs (`setfacl`) on shared scientific data.
   - Write only to its own scratch.
   - No interactive shell login.

   This single change reduces blast radius by ~95%. See the template
   request in [docs/operating-an-endpoint.md](docs/operating-an-endpoint.md#service-account-request-template).

2. **Multi-User Endpoint (MEP) with function allowlist.**
   Globus Compute can be configured to only execute pre-registered functions
   identified by SHA-256 hash. Convert the endpoint from "remote shell" into
   "bounded RPC." See [docs/operating-an-endpoint.md](docs/operating-an-endpoint.md#mep-allowlist).

3. **Globus Auth policy requiring high-assurance session.**
   Forces a recent MFA login at the configured IdP before submission. A
   stolen refresh token alone cannot submit.

4. **Slurm/PBS resource caps** on the endpoint user/account: `MaxJobs`,
   `MaxNodes`, `MaxWall`, `GrpTRES`. Bounds the damage of a runaway.

5. **Outbound network policy.** Most HPC login nodes allow arbitrary
   outbound HTTPS — including to attacker-controlled S3 buckets. If your
   site supports egress filtering or logging, use it.

6. **Container isolation.** Run worker code inside a Singularity/Apptainer
   image with read-only mounts of what's needed and no mount of `$HOME`.

7. **Audit logging.** Cron a weekly diff of submitted function hashes vs.
   the allowlist. Anomalies show up immediately.

### Threat model

We assume:
- The Globus Auth identity provider is not compromised.
- The endpoint host's kernel and filesystem ACLs are correctly enforcing
  the configured user's permissions.

We do **not** assume:
- That the MCP client is benign (it's an LLM — it may misinterpret prompts).
- That the network is private (TLS handles this — Globus uses HTTPS).
- That endpoint configuration files on disk are private. They aren't, by
  default. Protect them.

### Incident response

If you suspect endpoint compromise:

1. **Stop the endpoint** immediately:
   ```bash
   globus-compute-endpoint stop <name>
   ```
2. **Rotate Globus credentials** — log out at app.globus.org, revoke the
   consent for the endpoint, re-authenticate.
3. **Re-register the endpoint** with a new UUID. Distribute the new UUID
   out-of-band to known users.
4. **Audit the user's data** for unauthorized writes (`find -newer`,
   filesystem snapshots if available).
5. **Notify your site's security team.** ANL CELS, NCAR CISL, NERSC, etc.
   all want to know.

---

## Tool annotations and auto-approval

The server publishes MCP [tool annotations](https://modelcontextprotocol.io/)
(`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) so a
client can tell a query apart from something that moves data. Clients use
these to decide what to run without asking.

**They are advisory, not a security control.** The specification lets a client
ignore them entirely, and nothing here enforces them. Real enforcement is the
precondition layer, the endpoint's own `remote_read_root` / `remote_write_root`,
and the Globus consents behind both.

What the three categories mean in `src/uxarray_mcp/annotations.py`:

| Hint | Claim |
|---|---|
| `readOnlyHint: true` | No side effect anywhere — writes no file, mutates no session, submits no remote work. Not merely "does not write the file it was given". |
| `destructiveHint: true` | Can overwrite or relocate data the user cares about: a transfer landing on a cluster path, an export to a caller-supplied filename. |
| `openWorldHint: true` | The result depends on a machine we cannot see, so a failure is not necessarily a bug in the call. |

A tool that is not deliberately classified carries **no annotation at all**,
which clients read as "unknown". That is the honest default: a wrong
`readOnlyHint` is worse than a missing one, because it gets auto-approved and
the user never sees the prompt that would have caught it.

If you add a tool that writes anywhere, leave it out of `_READ_ONLY`. The
tests in `tests/test_tool_annotations.py` fail on a tool whose name implies a
write while claiming to be read-only, but naming is a heuristic and the
judgement is yours.

---

## Dependency security

This project sits on a large scientific stack — ~190 resolved packages once
extras and dev groups are counted — so most of the attack surface we carry is
someone else's code. Two jobs watch it, and they answer different questions:

| Job | Question it answers |
|---|---|
| `.github/workflows/audit.yml` | Does anything we pin have a published advisory? |
| `.github/dependabot.yml` | Is anything we pin simply out of date? |

The audit scans the **fully exported graph** (`uv export --all-extras
--all-groups`), not the installed environment. Dev-only and extra-only
packages run in CI and ship in the Docker image, so an advisory in one of them
is still ours. It runs on lockfile changes and weekly on a schedule, because
an advisory can be published against a version we already pin — no push would
ever trigger that.

Dependabot groups routine minor/patch bumps into one weekly PR, while security
updates arrive on their own so they are never queued behind routine churn.

### If the audit fails

1. Read which package and advisory. `osv-scanner` prints the OSV/GHSA id and
   the version that fixes it.
2. Try the cheap fix first: `uv lock --upgrade-package <name>`. Most
   advisories are resolved by a patch release already on PyPI.
3. Re-run the scan locally before pushing:
   ```bash
   uv export --format requirements-txt --no-hashes --all-extras --all-groups > /tmp/req.txt
   osv-scanner --lockfile=requirements.txt:/tmp/req.txt
   ```
4. If no fix exists upstream, judge exploitability **for this server** rather
   than in the abstract. A `starlette` form-parsing advisory matters to the
   OpenAPI transport and not at all to stdio; a `cryptography` issue matters
   wherever Globus auth runs. Record the reasoning in the PR — a suppression
   with no argument behind it is worse than a red check.

---

## Reporting a vulnerability in uxarray-mcp itself

Email `<maintainer email>` with details. Please do not file public issues
for security bugs until a fix is available.
