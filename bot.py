"""Entry point. Everything lives in the valstore package."""

import asyncio

from valstore.bot.app import main

if __name__ == "__main__":
    asyncio.run(main())
