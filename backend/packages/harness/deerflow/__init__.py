import sys

# Windows compatibility: psycopg (async PostgreSQL driver) only supports
# SelectorEventLoop, but Python on Windows defaults to ProactorEventLoop.
# Must set the policy BEFORE any event loop is created (i.e. at import time).
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
