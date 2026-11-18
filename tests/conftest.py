import asyncio
from pathlib import Path
import sys
from dotenv import load_dotenv

# 在 Windows 平台使用 SelectorEventLoop 防止 Proactor SSL 连接关闭时偶发的 'Event loop is closed'
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 加载项目根目录下的 .env 环境变量
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
