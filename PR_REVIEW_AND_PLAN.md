# PR Review and Reorganization Plan for `inspect-mesh-tool`

## Review Comments

### Strengths
- **Simple Implementation**: The logic is straightforward and uses `fastmcp` effectively to expose the `uxarray` functionality.
- **Dependency Management**: Uses `uv` and `pyproject.toml` which is modern and efficient.

### Areas for Improvement
1.  **Project Structure**:
    -   `test_local.py` is located in the root directory. It should be moved to a dedicated `tests/` directory to separate source code from test code.
    -   The entire application logic is contained within `src/uxarray_mcp/server.py`. As the project grows, this will become unmaintainable.
    -   Hardcoded paths in `test_local.py` make it difficult for other developers to run tests.

2.  **Testing**:
    -   The current "test" is a manual script (`test_local.py`) that prints to stdout.
    -   It relies on local files that may not exist on other machines (`Path.home() / "Desktop" ...`).
    -   There are no automated unit tests using a framework like `pytest`.
    -   There is no CI/CD configuration to run tests automatically.

3.  **Extensibility**:
    -   The `inspect_mesh` function mixes MCP-specific logic (decorators) with the core logic.
    -   Adding new tools would require modifying `server.py`, leading to a monolith.

4.  **Error Handling**:
    -   Error handling is basic (`try/except Exception`). It should be more specific.

## Proposed Reorganization Plan

To transform this into a "world-class", extensible repository, I propose the following structure and changes.

### 1. Improved Directory Structure

```text
uxarray-mcp-server/
├── .github/
│   └── workflows/
│       └── ci.yml              # CI workflow for tests and linting
├── src/
│   └── uxarray_mcp/
│       ├── __init__.py
│       ├── __main__.py
│       ├── server.py           # Entry point: constructs the MCP server
│       └── tools/              # Package for individual tools
│           ├── __init__.py
│           └── inspection.py   # Implementation of inspect_mesh
├── tests/                      # Dedicated tests directory
│   ├── __init__.py
│   ├── conftest.py             # Pytest fixtures (e.g., sample mesh data)
│   └── test_inspection.py      # Unit tests for inspection tool
├── pyproject.toml              # Updated with test/lint dependencies
└── README.md
```

### 2. Refactoring Logic

-   **`src/uxarray_mcp/tools/inspection.py`**: moving the `inspect_mesh` logic here.
    -   We can separate the *business logic* (getting grid stats) from the *MCP tool definition* if we want strictly hexagonal architecture, but for now, moving the tool function to its own module is a huge step forward.
-   **`src/uxarray_mcp/server.py`**: This file will:
    1.  Initialize the `FastMCP` server.
    2.  Import tools from `uxarray_mcp.tools`.
    3.  Register them (explicitly or via the decorator system if they are imported).

### 3. Testing Strategy (`pytest`)

-   **Unit Tests**:
    -   Mock `uxarray.open_grid` to return a `Mock` grid object with predefined attributes (`n_face`, `n_node`, etc.).
    -   This allows testing the `inspect_mesh` function's logic and return format without needing actual 5GB NetCDF files.
-   **Integration Tests**:
    -   Use small, synthetic mesh files (generated during tests or small assets in `tests/data`) to verify `uxarray` integration actually works.
-   **CI/CD**:
    -   Add a GitHub Action to run `pytest` and `ruff` (linter) on every PR.

### 4. Code Quality

-   **Type Hinting**: Ensure strict type hints are used.
-   **Docstrings**: Use Google or NumPy style docstrings.
-   **Linting**: Configure `ruff` in `pyproject.toml` to enforce style (imports, whitespace, etc.).

## Next Steps

If this plan is approved, I will:
1.  Create the `tests/` directory and skeleton test files.
2.  Create the `src/uxarray_mcp/tools/` directory.
3.  Move the `inspect_mesh` logic to `src/uxarray_mcp/tools/inspection.py`.
4.  Update `server.py` to use the refactored code.
5.  Setup `pytest` configuration in `pyproject.toml`.
