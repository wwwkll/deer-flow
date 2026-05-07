import sys

if sys.platform == "win32":
    import asyncio
    import uvicorn.loops.asyncio

    def _selector_loop_factory(use_subprocess: bool = False):
        return asyncio.SelectorEventLoop

    uvicorn.loops.asyncio.asyncio_loop_factory = _selector_loop_factory

from langgraph_cli.cli import cli

if __name__ == "__main__":
    cli()
