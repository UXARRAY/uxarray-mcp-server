"""Sphinx configuration for UXarray MCP Server documentation."""

import importlib.metadata
import sys
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DOCS_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"

sys.path.insert(0, str(SRC_DIR))

project = "UXarray MCP Server"
copyright = "2026, UXarray MCP Server Contributors"
author = "UXarray MCP Server Contributors"

try:
    release = importlib.metadata.version("uxarray-mcp")
except importlib.metadata.PackageNotFoundError:
    release = "0.1.0"

version = release

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "myst_parser",
]

# MyST (Markdown) settings
myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
]
myst_heading_anchors = 3

# Source file suffixes
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

templates_path = ["_templates"]
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    "onepager-uxarray-mcp.md",
]

# -- Options for HTML output -------------------------------------------------

html_theme = "sphinx_book_theme"
html_title = "UXarray MCP Server"
html_static_path = ["_static"]
html_css_files = ["custom.css"]

html_theme_options = {
    "repository_url": "https://github.com/UXARRAY/uxarray-mcp-server",
    "use_repository_button": True,
    "use_issues_button": True,
    "use_edit_page_button": True,
    "repository_branch": "main",
    "path_to_docs": "docs/",
    "home_page_in_toc": True,
    "show_navbar_depth": 2,
    "announcement": "You're on the <strong>MCP Server</strong> docs. "
    'Looking for UXarray? <a href="https://uxarray.readthedocs.io/">UXarray docs are here &rarr;</a>',
}

# Force light mode by default
html_context = {
    "default_mode": "light",
}

# -- Intersphinx mapping -----------------------------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "uxarray": ("https://uxarray.readthedocs.io/en/latest/", None),
}

# -- Autodoc settings --------------------------------------------------------

autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_mock_imports = []
