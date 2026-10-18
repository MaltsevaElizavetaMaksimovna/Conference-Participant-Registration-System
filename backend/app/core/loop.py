"""Фабрика event loop для Windows: psycopg async не работает на ProactorEventLoop.

uvicorn на Windows без --reload берёт Proactor, поэтому там запускать так:
    uvicorn app.main:app --loop app.core.loop:selector_loop_factory
На Linux/в Docker это не нужно.
"""

import asyncio


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()
