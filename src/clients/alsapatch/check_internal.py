import sys
from pathlib import Path
from typing import TYPE_CHECKING

def _is_patchbay_internal() -> bool:
    if not IS_INTERNAL:
        return False
    
    if TYPE_CHECKING:
        from daemon import patchbay_dmn_mng
    else:
        import patchbay_dmn_mng
        
    return patchbay_dmn_mng.is_internal()

IS_INTERNAL = not Path(sys.argv[0]).name == 'ray-alsapatch'
IS_PATCHBAY_INTERNAL = _is_patchbay_internal()