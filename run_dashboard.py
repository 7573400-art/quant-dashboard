import sys
import asyncio
import selectors
import os

# macOS python 3.9 kqueue 버그 우회용
if sys.platform == 'darwin':
    selector = selectors.SelectSelector()
    loop = asyncio.SelectorEventLoop(selector)
    asyncio.set_event_loop(loop)

from streamlit.web import cli

if __name__ == '__main__':
    sys.argv = ["streamlit", "run", "dashboard.py"]
    sys.exit(cli.main())
