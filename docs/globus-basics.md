# Globus, the short version

Ten minutes, a browser, no cost. Read this once before connecting a cluster.

## Which bit you need

Globus is several services. You need Auth (login) and Compute (runs your
code). You almost certainly do not need Transfer.

**Compute is not Transfer.** Different services, separate consents. A
working Compute endpoint cannot copy a file. If the word "consent" shows up
and you were not trying to move a file, you are in the wrong service.

The point of this server is that the analysis goes to the data and a number
comes back, so moving files is a separate decision:
[data-transfer.md](data-transfer.md).

## Get an identity

Already used Globus for HPC file transfers? You have one. Skip ahead.

Otherwise: go to <https://app.globus.org> and **sign in with your
institution** — Argonne, NCAR/UCAR, NERSC, most universities. Use the same
account that holds your HPC login.

That last part matters. A Globus identity is not automatically tied to your
cluster account. Sign in with a personal Google account when your HPC login
is `you@institution.edu` and you get an identity that authenticates fine and
then sees none of your endpoints — which looks exactly like a dead endpoint.
Already done it? Link the institutional identity at
<https://app.globus.org/account/identities> rather than starting over.

## Check it

```bash
uxarray-mcp doctor
uxarray-mcp endpoints discover
```

The first Globus command opens a browser. Finish the login and re-run.

`discover` asks Globus what your identity can see, which also answers *where
do I get a UUID?* — it is printed once when an endpoint registers and is easy
to lose. Nobody has to send you one.

| You see | Next |
|---|---|
| An endpoint listed | [connect-a-cluster.md](connect-a-cluster.md) |
| Nothing | [Create one](connect-a-cluster.md#create-20-minutes) |
| `ENDPOINT_NOT_ONLINE` | It is asleep — see below |
| A login loop | Wrong identity; see above |

## Three surprises

**An endpoint is per-user, not per-machine.** It runs as *your* cluster
account and reads what you can read. Your colleague's working endpoint tells
you nothing about whether you have one.

**Registered is not working.** It means a manager process phoned home. It
does not mean a worker exists, has `uxarray`, or can read your file. Those
fail separately, which is why `doctor`, `validate_hpc_setup` and
`probe_path_access` check them in that order.

**Endpoints sleep.** On a scheduler-backed endpoint the worker lives in a
batch allocation. When it ends, the endpoint stays registered with nothing to
run on. `ENDPOINT_NOT_ONLINE` usually means *ask again in a minute*. A slow
first call after an idle period is normal.

## One caution

An endpoint's operator can see the functions you submit and the paths you
name. Submit nothing you would not put in a ticket.
[SECURITY.md](https://github.com/UXARRAY/uxarray-mcp-server/blob/main/SECURITY.md)
has the rest.
