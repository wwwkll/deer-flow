import sys

if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        import uvicorn.loops.asyncio

        def _selector_loop_factory(use_subprocess: bool = False):
            return asyncio.SelectorEventLoop

        uvicorn.loops.asyncio.asyncio_loop_factory = _selector_loop_factory
    except ImportError:
        pass
