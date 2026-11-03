"""Launch using the existing environment; never install or fetch on startup."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_support import configure
configure()
from linux_app import main
raise SystemExit(main())
