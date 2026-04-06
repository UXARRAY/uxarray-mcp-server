UXarray MCP Server
==================

An MCP server that connects AI assistants like Claude to
`UXarray <https://uxarray.readthedocs.io/>`_ for analyzing unstructured
climate and weather meshes. Supports local execution and remote HPC
via Globus Compute.

New here? Start with :doc:`try-it` for the fastest verified path from clone
to real output. You can exercise the core tools and scientific agent with the
built-in ``healpix`` demo meshes before you wire up an MCP client.

Quick paths:

- :doc:`try-it` for a 2-minute smoke test and sample prompts
- :doc:`getting-started` to connect Claude Desktop or another MCP client
- :doc:`tools` to understand the server's tool surface and outputs

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   try-it
   getting-started
   tools
   hpc
   scientific-agent

.. toctree::
   :maxdepth: 2
   :caption: Reference

   Code Reference <api>
   architecture
   provenance

.. toctree::
   :maxdepth: 1
   :caption: Project

   changelog
