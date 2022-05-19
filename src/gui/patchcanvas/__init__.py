# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-

# # PatchBay Canvas engine using QGraphicsView/Scene
# # Copyright (C) 2010-2019 Filipe Coelho <falktx@falktx.com>
# # Copyright (C) 2019-2022 Mathieu Picot <picotmathieu@gmail.com>
# #
# # This program is free software; you can redistribute it and/or
# # modify it under the terms of the GNU General Public License as
# # published by the Free Software Foundation; either version 2 of
# # the License, or any later version.
# #
# # This program is distributed in the hope that it will be useful,
# # but WITHOUT ANY WARRANTY; without even the implied warranty of
# # MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# # GNU General Public License for more details.
# #
# # For a full copy of the GNU General Public License see the doc/GPL.txt file.

import logging

def make_logger():
    logger = logging.getLogger(__name__)
    log_handler = logging.StreamHandler()
    log_handler.setFormatter(logging.Formatter(
        f"%(name)s - %(levelname)s - %(message)s"))
    logger.setLevel(logging.WARNING)
    logger.addHandler(log_handler)

make_logger()

from .patchcanvas import *
