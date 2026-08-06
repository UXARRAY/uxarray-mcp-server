UXarray MCP Server
==================

An MCP server that connects AI assistants like Claude to
`UXarray <https://uxarray.readthedocs.io/>`_ for analyzing unstructured
climate and weather meshes. It runs locally by default; HPC execution via
Globus Compute is optional and only active once you configure an endpoint.

The same tools are served over MCP (for AI clients) or OpenAPI/REST (for
HTTP clients) from a single install.

.. toctree::
   :maxdepth: 2
   :caption: Getting started

   Local install (README) <https://github.com/UXARRAY/uxarray-mcp-server#readme>
   tools
   serving
   workflows
   scientific-agent

.. toctree::
   :maxdepth: 2
   :caption: Running on HPC (optional)

   remote-hpc
   operating-an-endpoint
   improv
   ucar
   chrysalis

.. toctree::
   :maxdepth: 2
   :caption: Reference

   Code Reference <api>
   architecture
   provenance
   release

.. toctree::
   :maxdepth: 1
   :caption: Project

   changelog
