import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# isolated DB, no background monitor, no LLM in tests
os.environ.setdefault("ORCA_DB_PATH", str(Path(tempfile.mkdtemp()) / "orca-test.db"))
os.environ["ORCA_MONITOR_ENABLED"] = "false"
os.environ["ORCA_LLM_ENABLED"] = "false"
