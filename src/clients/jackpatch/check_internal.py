import sys
from pathlib import Path

IS_INTERNAL = not Path(sys.argv[0]).name == 'ray-jackpatch'