import socket
import threading
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class P2PManager:
    def __init__(self, my_host, my_sync_port, peers):
        self.my_host = my_host
        self.my_sync_port = my_sync_port
        self.peers = peers # list of (host, port) tuples
        self.state_callback = None # Function to call when state is received
        self.running = True
        
        # Start listening for state updates
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.my_host, self.my_sync_port))
        self.server_socket.listen(5)
        
        self.accept_thread = threading.Thread(target=self._accept_connections, daemon=True)
        self.accept_thread.start()
        logging.info(f"P2P Sync listening on {self.my_host}:{self.my_sync_port}")

    def set_callback(self, callback):
        self.state_callback = callback

    def _accept_connections(self):
        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                threading.Thread(target=self._handle_peer, args=(conn,), daemon=True).start()
            except Exception as e:
                if self.running:
                    logging.error(f"P2P Acception error: {e}")

    def _handle_peer(self, conn):
        try:
            buffer = ""
            while self.running:
                data = conn.recv(65536).decode('utf-8')
                if not data:
                    break
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip() and self.state_callback:
                        try:
                            state = json.loads(line)
                            self.state_callback(state)
                        except json.JSONDecodeError:
                            pass
        except Exception as e:
            pass
        finally:
            conn.close()

    def broadcast_state(self, state_dict):
        """Send my current state to all peers."""
        msg = json.dumps(state_dict) + "\n"
        encoded_msg = msg.encode('utf-8')
        
        for peer in self.peers:
            host, port = peer
            try:
                # Try to connect and send the state
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    s.connect((host, port))
                    s.sendall(encoded_msg)
            except Exception as e:
                # It's expected that peers might be offline or disconnected
                pass

    def stop(self):
        self.running = False
        self.server_socket.close()
