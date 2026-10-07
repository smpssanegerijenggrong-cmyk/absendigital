"""Ensure editable project root is importable in both pytest CLI and python -m pytest."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
