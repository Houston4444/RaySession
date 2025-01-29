from osclib import Address
from nsm_client import NsmServer


class SlServer(NsmServer):
    def __init__(self, daemon_address: Address):
        super().__init__(daemon_address)
        
        self.wait_pong = False
        self.save_error = False
        self.load_error = False
        
        self.sl_addr = Address(9951)

        self.add_method('/sl_pong', 'ssi', self.sl_pong)
        self.add_method('/sl_save_error', None, self.sl_save_error)
        self.add_method('/sl_load_error', None, self.sl_load_error)

    def sl_pong(self, path: str, args: list, types: str, src_adrr: Address):
        self.wait_pong = False

    def sl_save_error(
            self, path: str, args: list, types: str, src_adrr: Address):
        self.save_error = True
        
    def sl_load_error(
            self, path: str, args: list, types: str, src_adrr: Address):
        self.load_error = True

    def set_sl_port(self, port: int):
        self.sl_addr = Address(port)
        
    def send_sl(self, *args):
        self.send(self.sl_addr, *args)