"""Portable ASCII entry point."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parent / '交付工具' / '运行交付版.py'), run_name='__main__')
