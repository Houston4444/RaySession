
import time

start_time = time.time()
import socket
sock_time = time.time() - start_time

import struct
from urllib.parse import urlparse

import cairo

bef_liblo = time.time()
import liblo
aft_liblo = time.time() - bef_liblo

import jack

print(sock_time)
print(aft_liblo)

class _OutgoingMessage:
    def __init__(self, oscpath):
        self.LENGTH = 4 #32 bit
        self.oscpath = oscpath
        self._args = []

    def write_string(self, val: str) -> bytes:
        dgram = val.encode('utf-8')
        diff = self.LENGTH - (len(dgram) % self.LENGTH)
        dgram += (b'\x00' * diff)
        return dgram

    def write_int(self, val: int) -> bytes:
        return struct.pack('>i', val)

    def write_float(self, val: int) -> bytes:
        return struct.pack('>f', val)

    def add_arg(self, argument):
        t = {str:"s", int:"i", float:"f"}[type(argument)]
        self._args.append((t, argument))

    def build(self) -> bytes:
        dgram = b''

        #OSC Path
        dgram += self.write_string(self.oscpath)

        if not self._args:
            dgram += self.write_string(',')
            return dgram

        # Write the parameters.
        arg_types = "".join([arg[0] for arg in self._args])
        dgram += self.write_string(',' + arg_types)
        for arg_type, value in self._args:
            f = {"s":self.write_string, "i":self.write_int, "f":self.write_float}[arg_type]
            dgram += f(value)
        return dgram


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #internet, udp
sock.bind(('', 0)) #pick a free port on localhost.
sock.setblocking(False)
msg = _OutgoingMessage("/ray/client/resume")
msg.add_arg('carla_2')  #s:clientId
parsed = urlparse('osc.udp://houstonbureau:16187/')
sock.sendto(msg.build(), (parsed.hostname, parsed.port))