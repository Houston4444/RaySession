import signal
import sys

from qtpy.QtCore import QTimer, Qt
from qtpy.QtWidgets import QApplication, QMainWindow, QAction, QToolBar, QFileDialog

def signal_handler(sig, frame):
    QApplication.quit()


def action_cliec(*args, **kwargs):
    print('zoeif', args, kwargs)
    fil = QFileDialog.getOpenFileName(
        None, 'tralala', options=QFileDialog.Option.DontUseNativeDialog)
    print(fil)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_win = QMainWindow()
    
    act_show_file = QAction('zfef')
    act_show_file.triggered.connect(action_cliec)
    tool_bar = QToolBar(main_win)
    menu_bar = main_win.addToolBar(Qt.ToolBarArea.TopToolBarArea, tool_bar)
    tool_bar.addAction(act_show_file)
    
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    timer = QTimer()
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()
    
    main_win.show()
    app.exec()
    
    print('Opdone')
    