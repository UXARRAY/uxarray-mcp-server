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

## Reporting a vulnerability in uxarray-mcp itself

Email `<maintainer email>` with details. Please do not file public issues
for security bugs until a fix is available.
