import socket
import time

DEFAULT_SIZE = 1024
DEFAULT_TIMEOUT=20

class Udp(object):
    
    def __init__(self, ip, port):
        self._ip = ip
        self._port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    def _get_settings(self, ip, port):
        if ip is None:
            ip = self._ip
        if port is None:
            port = self._port
        return (ip, port)
    
    def set_broadcast(self, enable=True):
        flag = 0
        if enable:
            flag = 1
        
        rc = self._sock.setsockopt(socket.SOL_SOCKET,
                                   socket.SO_BROADCAST,
                                   flag)
        return (rc == 0)
    
    def set_timeout(self, timeout=None):
        self._sock.settimeout(timeout)
    
    def broadcast(self, msg, port=None, addr=None):
        # TODO: Maybe add auto-enable for broadcasting...
        if addr is None:
            addr = self._get_settings(None, port)
        addr = ('<broadcast>', addr[1])
        self._sock.sendto(msg, addr)
    
    def bind(self, ip=None, port=None):
        addr = self._get_settings(ip, port)
        self._sock.bind(addr)
    
    def send(self, msg, ip=None, port=None, addr=None):
        if addr is None:
            addr = self._get_settings(ip, port)
        self._sock.sendto(msg, addr)
    
    def recv(self, size=DEFAULT_SIZE):
        data, addr = self._sock.recvfrom(size)
        return (data, addr)
    
    def close(self):
        self._sock.close()



def main ():
    while True:
        u = Udp('', 4298)
        try:
            u.bind(port=4297)
            u.set_broadcast(True)
            u.set_timeout(10.0)
            try:
                u.broadcast("Hello everybody!\n")
            except socket.error:
                print "Socket error, try again ... "
                continue
            try:
                data, addr = u.recv()
                print "[%s]: %s" % (addr, data)
            except socket.timeout:
                print "Timed out..."
            time.sleep (4)
        except KeyboardInterrupt:
            print "Exit"
            return
        finally:
            u.close()

if __name__ == '__main__' :
    main()
