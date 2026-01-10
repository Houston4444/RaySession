import sys
from pathlib import Path
import signal


# import liblo

# import custom pyjacklib and shared
sys.path.insert(1, str(Path(__file__).parents[2] / 'HoustonPatchbay/source'))
sys.path.insert(1, str(Path(__file__).parents[1] / 'shared'))
sys.path.insert(1, str(Path(__file__).parents[1] / 'gui'))

# import base_enums

# from osclib import Address, OscPack



print(sys.path)

from proc_name import set_proc_name
# third party imports
from qtpy.QtWidgets import QApplication
# from qtpy.QtGui import QIcon, QFontDatabase
from qtpy.QtCore import QLocale, QTranslator, QTimer, QLibraryInfo

# Imports from src/shared
import ray

# # Local imports
from gui_tools import (ArgParser, CommandLineArgs,
                       init_gui_tools, get_code_root)
from gui_server_thread import GuiServerThread
from gui_tcp_thread import GuiTcpThread
from gui_session import SignaledSession

# prevent to not find icon at startup
import resources_rc

# import patchbay
# import add_application_dialog
# import child_dialogs
# import client_prop_adv_dialog
# import client_properties_dialog
# import daemon_manager
# import gui_client
# import gui_server_thread
# import gui_session
# import gui_signaler
# import gui_tcp_thread
# import gui_tools
# import list_widget_clients
# import list_widget_preview_clients
# import main_window
# import nsm_child
# import open_session_dialog
# import preferences_dialog
# import ray_patchbay_manager
# # import raysession
# import resources_rc
# import snapshots_dialog
# import promoted_widgets
# import utility_scripts

set_proc_name('ray_foot_mem')

def signal_handler(sig, frame):
    QApplication.quit()
    
if __name__ == '__main__':
    # connect SIGINT and SIGTERM
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # set Qt Application
    app = QApplication(sys.argv)
    # app.setApplicationName(ray.APP_TITLE)
    # app.setApplicationVersion(ray.VERSION)
    # app.setOrganizationName(ray.APP_TITLE)
    # app.setWindowIcon(QIcon(
    #     f':main_icon/scalable/{ray.APP_TITLE.lower()}.svg'))
    # app.setQuitOnLastWindowClosed(False)
    # app.setDesktopFileName(ray.APP_TITLE.lower())

    # # with some themes (GNOME fedora 34)
    # # QGroupBox are not really visible
    # # app.setStyleSheet("QGroupBox{background-color: #15888888}")

    # ### Translation process
    # locale = QLocale.system().name()

    # # app_translator = QTranslator()
    # # if app_translator.load(QLocale(), ray.APP_TITLE.lower(),
    # #                        '_', str(get_code_root() / 'locale')):
    # #     app.installTranslator(app_translator)

    # # patchbay_translator = QTranslator()
    # # if patchbay_translator.load(
    # #         QLocale(), 'patchbay',
    # #         '_', str(Path(__file__).parents[2] / 'HoustonPatchbay' / 'locale')):
    # #     app.installTranslator(patchbay_translator)

    # # sys_translator = QTranslator()
    # # path_sys_translations = QLibraryInfo.location(
    # #     QLibraryInfo.TranslationsPath)
    # # if sys_translator.load(QLocale(), 'qt', '_', path_sys_translations):
    # #     app.installTranslator(sys_translator)

    # QFontDatabase.addApplicationFont(":/fonts/Ubuntu-R.ttf")
    # QFontDatabase.addApplicationFont(":/fonts/Ubuntu-C.ttf")

    # # # get arguments
    # # parser = ArgParser()

    # # init_gui_tools()

    # # Add raysession/src/bin to $PATH
    # # to can use raysession after make, without install
    # # ray.add_self_bin_to_path()

    # # Translation process
    # locale = QLocale.system().name()
    # # appTranslator = QTranslator()

    # # if appTranslator.load(
    # #     str(Path(__file__).parents[2] / 'locale' / f'raysession_{locale}')):
    # #     app.installTranslator(appTranslator)

    # _translate = app.translate

    # needed for SIGINT and SIGTERM
    timer = QTimer()
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()

    app.exec()

    # for i in range(1000):
    #     time.sleep(0.010)