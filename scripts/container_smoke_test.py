"""End-to-end smoke test for the container image over real MCP stdio.

An import check proves the dependency closure resolves. It does not prove the
server speaks MCP, that the tool surface is non-empty, or that a tool can open
a file and return a number -- which are the three things that actually have to
work. This drives the container the way a real client does: spawn it, complete
the initialize handshake, list tools, then call one that does genuine numerical
work against a baked fixture and check the answer.

Usage::

    python3 scripts/container_smoke_test.py [--image uxarray-mcp:local]

Exit code is 0 only if every check passes.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time

PROTOCOL_VERSION = "2025-06-18"

# The global fixture is a structured 18 x 9 lon/lat mesh on a unit sphere.
# Its faces tile the whole sphere exactly once, so total area must be 4*pi.
# That is an analytic ground truth, not a recorded snapshot -- if the area
# code regresses, this number cannot follow it.
EXPECTED_TOTAL_AREA = 4.0 * math.pi

# Tolerance is 1e-4, not machine epsilon, and the gap is physics rather than
# sloppiness: UXarray integrates each face with a finite-order quadrature, so
# a coarse 20-degree mesh recovers 4*pi to about 2e-6 relative. Measured drift
# on this fixture is 2.0e-6. Asserting 1e-6 here would fail on a correct
# result; asserting 1e-2 would let a real regression through. 1e-4 sits about
# a decade and a half above the discretization floor -- tight enough to catch
# a wrong radius, a dropped face, or a degrees/radians slip, all of which move
# the answer by percent or more.
AREA_RTOL = 1e-4


class Client:
    """Minimal MCP stdio client: newline-delimited JSON-RPC over a pipe."""

    def __init__(self, image: str) -> None:
        self.proc = subprocess.Popen(
            ["docker", "run", "--rm", "-i", image],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._id = 0

    def call(self, method: str, params: dict | None = None, timeout: float = 120.0):
        self._id += 1
        request = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            request["params"] = params
        self._send(request)
        return self._recv(self._id, timeout)

    def notify(self, method: str, params: dict | None = None) -> None:
        request = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            request["params"] = params
        self._send(request)

    def _send(self, payload: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def _recv(self, want_id: int, timeout: float):
        """Read until the response with our id arrives.

        Skips notifications and any server-initiated traffic rather than
        assuming the next line is ours -- a server that logs progress
        notifications would otherwise break this client.
        """
        assert self.proc.stdout is not None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                stderr = self.proc.stderr.read() if self.proc.stderr else ""
                raise RuntimeError(f"server closed the pipe. stderr:\n{stderr}")
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                # Stray non-JSON on stdout is itself a bug worth surfacing,
                # but it should not wedge the test.
                print(f"    [warn] non-JSON on stdout: {line[:120]}")
                continue
            if message.get("id") == want_id:
                return message
        raise TimeoutError(f"no response to id={want_id} within {timeout}s")

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def _unwrap(result: dict) -> dict:
    """Pull the tool payload out of an MCP tools/call result.

    Prefers structuredContent; falls back to parsing the text block, since
    whether a server emits structured output depends on its schema support.
    """
    if "structuredContent" in result:
        return result["structuredContent"]
    for block in result.get("content", []):
        if block.get("type") == "text":
            try:
                return json.loads(block["text"])
            except json.JSONDecodeError:
                return {"_raw_text": block["text"]}
    return {}


def _find(obj, key: str):
    """Depth-first search for the first occurrence of ``key``.

    The response envelope carries provenance and contract metadata around the
    payload, and its exact nesting is not this test's business to hard-code.
    """
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            hit = _find(value, key)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for item in obj:
            hit = _find(item, key)
            if hit is not None:
                return hit
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="uxarray-mcp:local")
    args = parser.parse_args(argv)

    failures: list[str] = []
    delim = "-" * 62

    print(f"Smoke-testing {args.image}")
    print(delim)

    started = time.monotonic()
    client = Client(args.image)

    try:
        # 1 -- handshake
        response = client.call(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "container-smoke-test", "version": "1.0"},
            },
        )
        if "error" in response:
            print(f"[FAIL] initialize: {response['error']}")
            return 1
        info = response["result"].get("serverInfo", {})
        ready = time.monotonic() - started
        print(f"[ OK ] initialize -> {info.get('name')} {info.get('version', '')}")
        print(f"       cold start to ready: {ready:.1f}s")
        client.notify("notifications/initialized")

        # 2 -- tool surface
        response = client.call("tools/list")
        tools = response.get("result", {}).get("tools", [])
        names = {t["name"] for t in tools}
        if not tools:
            failures.append("tools/list returned an empty surface")
            print("[FAIL] tools/list: no tools")
        else:
            print(f"[ OK ] tools/list -> {len(tools)} tools")

        # 3 -- the container must expose its own baked data. If list_datasets
        #      cannot see /data/uxarray the fixtures are unreachable and the
        #      image is useless for demos and harnesses alike.
        # Namespaced: the registry groups IO tools under an "io" namespace,
        # so the wire name is "io-list_datasets", not "list_datasets".
        if "io-list_datasets" in names:
            response = client.call(
                "tools/call",
                {
                    "name": "io-list_datasets",
                    "arguments": {"directory": "/data/uxarray"},
                },
            )
            payload = _unwrap(response.get("result", {}))
            total = _find(payload, "total_files") or 0
            if total >= 10:
                print(f"[ OK ] list_datasets -> {total} files in /data/uxarray")
            else:
                failures.append(f"list_datasets saw {total} files, expected >= 10")
                print(f"[FAIL] list_datasets -> {total} files")
        else:
            failures.append("io-list_datasets missing from the tool surface")
            print("[FAIL] io-list_datasets not exposed")

        # 4 -- real numerics against an analytic ground truth.
        if "run_analysis" in names:
            response = client.call(
                "tools/call",
                {
                    "name": "run_analysis",
                    "arguments": {
                        "operation": "calculate_area",
                        "grid_path": "/data/uxarray/global_grid.nc",
                    },
                },
                timeout=180.0,
            )
            result = response.get("result", {})
            payload = _unwrap(result)
            if response.get("error") or result.get("isError"):
                failures.append(f"run_analysis errored: {str(payload)[:200]}")
                print(f"[FAIL] run_analysis: {str(payload)[:200]}")
            else:
                total_area = _find(payload, "total_area")
                if total_area is None:
                    failures.append("run_analysis returned no total_area")
                    print(f"[FAIL] run_analysis: no total_area in {str(payload)[:200]}")
                elif math.isclose(
                    float(total_area), EXPECTED_TOTAL_AREA, rel_tol=AREA_RTOL
                ):
                    print(
                        f"[ OK ] run_analysis(calculate_area) -> {float(total_area):.9f} "
                        f"== 4*pi ({EXPECTED_TOTAL_AREA:.9f})"
                    )
                else:
                    failures.append(
                        f"total_area {total_area} != 4*pi {EXPECTED_TOTAL_AREA}"
                    )
                    print(f"[FAIL] total_area {total_area} != 4*pi")
        else:
            failures.append("run_analysis missing from the tool surface")
            print("[FAIL] run_analysis not exposed")

    finally:
        client.close()

    print(delim)
    if failures:
        print(f"FAILED ({len(failures)}):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
