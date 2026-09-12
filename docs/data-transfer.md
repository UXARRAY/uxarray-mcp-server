# Moving Files — Globus Transfer

Globus Compute and Globus Transfer are two services. Compute runs code where
the data already is; Transfer copies files between machines. They have separate
logins and separate consents, so **being able to run a job on a cluster does not
let you copy a file to it**, and a working `uxarray-mcp doctor` says nothing
about whether a transfer will succeed.

Most people never need this page. Remote analysis is the point of the HPC
support — you leave the data where it is and get a number or a plot back. Set
transfers up when you actually have a file to move: a small input to stage in,
or a result to bring home.

## What you get

Four tools, once it is configured:

| tool | does |
|---|---|
| `transfer_ls` | list a directory on the cluster |
| `transfer_put` | upload a file from this machine |
| `transfer_get` | download a file to this machine |
| `transfer_status` | poll a task to `SUCCEEDED` or `FAILED` |

Transfers are asynchronous. `transfer_put` and `transfer_get` return a task ID
immediately; `transfer_status` is how you find out what happened.

## Setup

```bash
uv tool install --python 3.12 --extra transfer uxarray-mcp
uxarray-mcp transfer setup --endpoint NAME
```

`NAME` is the endpoint you already registered with `endpoints add` (see
[remote-hpc.md](remote-hpc.md)).

The command walks seven prerequisites, says which already hold, and offers to
fix the rest. Add `--check` to report without changing or asking anything:

```text
  [ok  ] globus CLI -- /opt/homebrew/bin/globus
  [TODO] globus login -- not logged in
         fix: globus login
  [ok  ] facility collection -- NCAR GLADE  d33b3614-6d04-11e5-ba46-22000b92c6ec
  [ok  ] Globus Connect Personal -- running
  [TODO] /Users/you writable -- /Users/you is shared READ-ONLY, so downloads here will be refused
         fix: Globus Connect Personal -> Preferences -> Access, select /Users/you,
              tick Writable, then restart it
  [ok  ] this machine's collection -- 58bfc3d1-...
  [ok  ] config -- ucar-uxarray-yac in ~/.config/uxarray-mcp/config.yaml
```

### This package stores no credentials

Every authentication step is handed to the [`globus` command-line
client](https://docs.globus.org/cli/), which already owns your tokens, your
consents and your session. That is deliberate. Globus auth has scopes that exist
on one kind of collection and not another, and identity policies that only
surface after a transfer has been submitted; those rules change, and the CLI
already tracks them. Nothing here holds a token, and `uxarray-mcp transfer
setup` runs `globus login` rather than reimplementing it.

The consequence worth knowing: the login is shared with anything else you use
the `globus` CLI for, and `globus logout` breaks transfers here too.

### Both ends need a collection

A transfer is between two *collections*, and a collection UUID is not an
endpoint UUID — a Globus Compute endpoint ID says nothing about which collection
serves the filesystem it runs on.

The facility end is looked up from a table for NCAR, ALCF Polaris, ALCF Aurora
and NERSC; anywhere else, the command asks and you paste the UUID from
**Collections** in the [Globus web app](https://app.globus.org). Searching by
name is a trap: facilities publish a guest collection per project and users
publish their own, so "GLADE" matches a page of look-alikes.

Your end is [Globus Connect
Personal](https://www.globus.org/globus-connect-personal), which makes your
laptop a collection. `transfer setup` reads its UUID out of
`~/.globusonline/lta/client-id.txt` so you do not have to find it.

### The write bit

Globus Connect Personal's default share is your home directory **read-only**,
and nothing warns you. Uploads work, because they only read here. Downloads fail
on the destination write, hours later, with `PERMISSION_DENIED` — which reads
like a network problem and is not. `transfer setup` checks this on both macOS
and Linux and is the reason the command exists.

## Paths

`remote_write_root` is a containment boundary, not a default directory. A path
outside it is refused, not relocated into it. `remote_read_root` widens what may
be read without widening what may be written — the usual case is a project tree
you can read and one scratch subtree you can write.

Relative paths resolve against those roots on the remote side and against
`local_root` on this side. Absolute paths are checked against the roots and
refused if they fall outside, so `transfer_ls('/etc/passwd')` comes back as a
refusal rather than a listing.

The config block `transfer setup` writes:

```yaml
hpc:
  endpoints:
    ucar-uxarray-yac:
      endpoint_id: ...
      globus_transfer:
        remote_collection_id: d33b3614-6d04-11e5-ba46-22000b92c6ec
        local_collection_id: 58bfc3d1-...
        remote_write_root: /glade/derecho/scratch/you
        remote_read_root: /glade
        local_root: /Users/you
```

Some collections expose a subtree as their own `/`. `collection_roots` lists the
filesystem prefixes to strip, so `/lus/eagle/projects/x/run.nc` is sent as
`/x/run.nc`. Paths under no configured root are passed through unchanged: a
wrong translation is worse than none, because Globus rejects a path it does not
recognise but happily reads a rewritten one that names the wrong real file.

## When it breaks

Run `uxarray-mcp doctor --endpoint NAME`. Its `transfer` check reports the
collections, the roots, and whether your local share is writable.

Three failures look unrelated and are the same problem — no tokens, no consent
for a collection's `data_access` scope, and a session identity the collection
refuses. All three need a browser, which an MCP server does not have, so they
surface as one error telling you to run `uxarray-mcp transfer setup` in a
terminal.

A task that reaches `nice_status: TIMEOUT` on `STOR` is usually neither, and
usually not dead either. Globus negotiates data channels on ports separate from
the control connection, retries them on its own, and reports `TIMEOUT` while it
is still trying; a task that sat there for twenty minutes has been observed to
finish `SUCCEEDED`. Poll `transfer_status` before concluding anything. A
corporate VPN is the usual reason for the retries — it degrades the data
channel without blocking it — so if the duration is wildly out of proportion to
the file, compare one transfer off the VPN.
