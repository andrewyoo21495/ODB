"""Interface-independent use-case services.

These modules contain the core logic of each hub feature, decoupled from any
particular interface (CLI, web API, MCP).  Each service function takes plain
arguments and returns data structures; it must not depend on argparse, stdout
formatting, or any GUI toolkit.

Optional ``log`` callbacks (``Callable[[str], None]``) let callers redirect
progress messages — defaulting to ``print`` preserves CLI behaviour.
"""
