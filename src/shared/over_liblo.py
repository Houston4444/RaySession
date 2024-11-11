
try:
    import liblo
    from liblo import Message
except ImportError:
    import pyliblo3 as liblo
    from pyliblo3 import Message

def make_method(*args, **kwargs):
    return liblo.make_method(*args, **kwargs)


class Server(liblo.Server):
    url: str
    
    def __init__(self, *args, **kwargs):
        liblo.Server.__init__(self, *args, **kwargs)

    def add_method(self, *args, **kwargs):
        return liblo.Server.add_method(self, *args, **kwargs)
        
    def recv(self, *args, **kwargs):
        return liblo.Server.recv(self, *args, **kwargs)

    def send(self, *args, **kwargs):
        return liblo.Server.send(self, *args, **kwargs)


class ServerThread(liblo.ServerThread):
    url: str

    def __init__(self, *args, **kwargs):
        liblo.ServerThread.__init__(self, *args, **kwargs)

    def add_method(self, *args, **kwargs):
        return liblo.ServerThread.add_method(self, *args, **kwargs)
    
    def send(self, *args, **kwargs):
        return liblo.ServerThread.send(self, *args, **kwargs)

''' seems impossible to overinstance Message,
    it may be checked with type() function'''
class Message(liblo.Message):
    def __init__(self, *args, **kwargs):
        liblo.Message(self, *args, **kwargs)


class Address(liblo.Address):
    hostname: str
    url: str
    port: int
    
    def __init__(self, *args):
        liblo.Address.__init__(self, *args)
    
