import os
from PyQt5.QtCore import QCoreApplication, QStandardPaths

def dirname(*args):
    return os.path.dirname(*args)

def getAppConfigPath():
    return "%s/%s" % (
            QStandardPaths.writableLocation(QStandardPaths.ConfigLocation),
            QCoreApplication.organizationName())

class TemplateRoots():
    _factory_root = dirname(dirname(dirname(os.path.realpath(__file__))))
    
    net_session_name = ".ray-net-session-templates"
    factory_sessions = "%s/session_templates" % _factory_root
    factory_clients  = "%s/client_templates"  % _factory_root
    user_sessions    = "%s/session_templates" % getAppConfigPath()
    user_clients     = "%s/client_templates"  % getAppConfigPath()
    
    @classmethod
    def initConfig(cls, config_path=''):
        cls.user_sessions = "%s/session_templates" % getAppConfigPath()
        cls.user_clients  = "%s/client_templates"  % getAppConfigPath()
        
    
        
