import sys
from pathlib import Path
import time
import signal
import xml.etree.ElementTree as ET
import json
import logging
from enum import Enum, IntEnum, IntFlag, auto
from typing import Any, Union, Optional, Iterator
from dataclasses import dataclass
import functools
import shutil
import os
import socket
import shlex

from qtpy.QtCore import QCoreApplication, QTimer, QLocale, QTranslator
from qtpy.QtGui import QIcon
from qtpy.QtCore import (
    QSettings, QDataStream, QIODevice, QUrl, QByteArray)

import jack

# import liblo

# import custom pyjacklib and shared
sys.path.insert(1, str(Path(__file__).parents[2] / 'HoustonPatchbay'))
sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))
sys.path.insert(1, str(Path(__file__).parents[1] / 'daemon'))

# import base_enums

from osclib import Address, OscPack

from osc_server_thread import OscServerThread, Gui
# from tcp_server_thread import TcpServerThread

# from server_sender import ServerSender
# from daemon_tools  import (
#     TemplateRoots, Terminal, RS, get_code_root,
#     highlight_text, exec_and_desktops)
# from signaler import Signaler
# from scripter import ClientScripter

import ardour_templates
import bookmarker
# import canvas_saver
# import client
# import daemon_tools
# import desktops_memory
# import file_copier
# import multi_daemon_file
# import osc_server_thread
# import patch_rewriter
# # import ray_daemon
# import scripter
# import server_sender
# import session
# import session_signaled
# import signaler
# import snapshoter
# import tcp_server_thread
# import templates_database
# import terminal_starter


# import patchbay.patchcanvas.patshared.group_pos
# import patchbay.patchcanvas.patshared.json_tools
# import patchbay.patchcanvas.patshared.portgroups_dict
# import patchbay.patchcanvas.patshared.pretty_names
# import patchbay.patchcanvas.patshared.views_dict


# from patshared import (
#     PortgroupsDict, from_json_to_str, PortTypesViewFlag, GroupPos,
#     PortgroupMem, ViewsDict)
print(sys.path)

from proc_name import set_proc_name



set_proc_name('ray_foot_mem')

def signal_handler(sig, frame):
    QCoreApplication.quit()
    
if __name__ == '__main__':
    # connect SIGINT and SIGTERM
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    app = QCoreApplication(sys.argv)

    # Translation process
    locale = QLocale.system().name()
    appTranslator = QTranslator()

    if appTranslator.load(
        str(Path(__file__).parents[2] / 'locale' / f'raysession_{locale}')):
        app.installTranslator(appTranslator)

    _translate = app.translate

    # needed for SIGINT and SIGTERM
    timer = QTimer()
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()

    app.exec()

    # for i in range(1000):
    #     time.sleep(0.010)