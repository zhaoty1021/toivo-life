"""让 `python -m toivo ...` 直接调用 CLI"""
from .cli import main
import sys
sys.exit(main())
