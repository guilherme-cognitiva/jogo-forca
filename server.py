import socket
import threading
import json
import logging
import time
import argparse
import uuid
import sys

from models import GameState, PlayerState
import game_engine
from p2p_sync import P2PManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class HangmanServer:
    def __init__(self, host, port, sync_port, peers):
        self.host = host
        self.port = port
        
        # State
        self.state_lock = threading.Lock()
        self.games = {} # game_id -> GameState
        self.waiting_queue = [] # list of player_id
        self.last_updated = 0.0
        
        # Network tracking
        self.clients = {} # player_id -> conn object (Only local connected clients)
        
        # P2P
        self.p2p = P2PManager(host, sync_port, peers)
        self.p2p.set_callback(self.on_p2p_state_received)
        
        # Socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(10)
        self.running = True
        
        # Threads
        self.accept_thread = threading.Thread(target=self._accept_connections, daemon=True)
        self.timeout_thread = threading.Thread(target=self._timeout_checker, daemon=True)
        
    def start(self):
        self.accept_thread.start()
        self.timeout_thread.start()
        logging.info(f"Server listening for clients on {self.host}:{self.port}")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Shutting down server...")
            self.running = False
            self.server_socket.close()
            self.p2p.stop()
            sys.exit(0)

    def _sync_state(self):
        """Called WITH lock held. Increments clock and broadcasts."""
        self.last_updated = time.time()
        state_dict = {
            'last_updated': self.last_updated,
            'games': {k: v.to_dict() for k, v in self.games.items()},
            'waiting_queue': self.waiting_queue
        }
        self.p2p.broadcast_state(state_dict)

    def on_p2p_state_received(self, state_dict):
        with self.state_lock:
            remote_time = state_dict.get('last_updated', 0)
            if remote_time > self.last_updated:
                self.last_updated = remote_time
                self.games = {k: GameState.from_dict(v) for k, v in state_dict.get('games', {}).items()}
                self.waiting_queue = state_dict.get('waiting_queue', [])
                logging.info("State synchronized from peer.")
                
                self._notify_local_clients()

    def _notify_local_clients(self):
        """Broadcasts current state to all locally connected clients."""
        for player_id, conn in list(self.clients.items()):
            if player_id in self.waiting_queue:
                pos = self.waiting_queue.index(player_id) + 1
                self.send_to_client(player_id, {'type': 'waiting', 'position': pos})
            else:
                for game_id, game in self.games.items():
                    if player_id in game.players:
                        self._send_game_state(player_id, game)
                        break

    def _send_game_state(self, player_id, game: GameState):
        player = game.players[player_id]
        msg = {
            'type': 'game_state',
            'status': player.status,
            'word_state': game_engine.get_masked_word(game.word, player.guessed_letters),
            'wrong_count': player.wrong_count,
            'guessed': list(player.guessed_letters),
        }
        if player.opponent_id:
            opponent = game.players.get(player.opponent_id)
            if opponent:
                msg['opponent_wrong'] = opponent.wrong_count
                msg['opponent_status'] = opponent.status
                msg['opponent_word_state'] = game_engine.get_masked_word(game.word, opponent.guessed_letters)
                
                if game.status == 'finished' or player.status in ['won', 'lost']:
                    msg['full_word'] = game.word
                    msg['winner'] = game.winner_id
        
        self.send_to_client(player_id, msg)

    def send_to_client(self, player_id, msg):
        conn = self.clients.get(player_id)
        if conn:
            try:
                data = json.dumps(msg) + '\n'
                conn.sendall(data.encode('utf-8'))
            except Exception:
                pass # Handled by the thread that reads from client

    def _accept_connections(self):
        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
            except Exception as e:
                pass

    def handle_client(self, conn, addr):
        logging.info(f"New connection from {addr}")
        player_id = None
        buffer = ""
        
        try:
            while self.running:
                data = conn.recv(4096).decode('utf-8')
                if not data:
                    break
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        try:
                            msg = json.loads(line)
                            
                            if msg.get('type') == 'connect':
                                player_id = msg.get('player_id')
                                if not player_id:
                                    player_id = str(uuid.uuid4())
                                
                                with self.state_lock:
                                    self.clients[player_id] = conn
                                    # Send ACK
                                    conn.sendall((json.dumps({"type": "connected", "player_id": player_id}) + "\n").encode('utf-8'))
                            
                            with self.state_lock:
                                changed = self.process_client_message(conn, player_id, msg)
                                if changed:
                                    self._sync_state()
                                    self._notify_local_clients()
                        except json.JSONDecodeError:
                            pass
        except Exception as e:
            pass
        finally:
            conn.close()
            if player_id:
                with self.state_lock:
                    self._handle_client_disconnect(player_id)
                    self._sync_state()
                    self._notify_local_clients()

    def process_client_message(self, conn, player_id, msg):
        msg_type = msg.get('type')
        if msg_type == 'connect':
            # Reconnect logic
            reconnected = False
            for game in self.games.values():
                if player_id in game.players:
                    player = game.players[player_id]
                    if player.status == 'disconnected':
                        player.status = 'playing'
                        player.disconnect_time = None
                        reconnected = True
                    break
            
            if not reconnected and player_id not in self.waiting_queue:
                self.waiting_queue.append(player_id)
            
            self._check_matchmaking()
            return True
            
        elif msg_type == 'guess':
            if not player_id:
                return False
            letter = msg.get('letter')
            if not letter:
                return False
                
            for game in self.games.values():
                if player_id in game.players:
                    changed = game_engine.process_guess(game, player_id, letter)
                    return changed
                    
        return False

    def _check_matchmaking(self):
        while len(self.waiting_queue) >= 2:
            p1_id = self.waiting_queue.pop(0)
            p2_id = self.waiting_queue.pop(0)
            
            new_game = game_engine.create_game(p1_id, p2_id)
            self.games[new_game.game_id] = new_game
            logging.info(f"Match created! {p1_id} vs {p2_id}")

    def _handle_client_disconnect(self, player_id):
        if player_id in self.clients:
            del self.clients[player_id]
            
        if player_id in self.waiting_queue:
            self.waiting_queue.remove(player_id)
            logging.info(f"Player {player_id} left queue.")
        else:
            for game in self.games.values():
                if player_id in game.players:
                    player = game.players[player_id]
                    if player.status in ['playing', 'waiting']:
                        player.status = 'disconnected'
                        player.disconnect_time = time.time()
                        logging.info(f"Player {player_id} disconnected from game {game.game_id}.")
                        break

    def _timeout_checker(self):
        while self.running:
            time.sleep(5)
            with self.state_lock:
                changed = False
                for game in self.games.values():
                    if game_engine.check_disconnect_timeouts(game, timeout_seconds=30):
                        changed = True
                if changed:
                    self._sync_state()
                    self._notify_local_clients()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Hangman Distribuited Server")
    parser.add_argument('--port', type=int, default=5000, help="Client connection port")
    parser.add_argument('--sync-port', type=int, default=6000, help="P2P Server sync port")
    parser.add_argument('--peers', type=str, default="", help="Comma separated list of host:port for peer sync")
    
    args = parser.parse_args()
    
    peer_list = []
    if args.peers:
        for p in args.peers.split(','):
            h, p_port = p.split(':')
            peer_list.append((h, int(p_port)))
            
    server = HangmanServer('0.0.0.0', args.port, args.sync_port, peer_list)
    server.start()
