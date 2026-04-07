import socket
import threading
import json
import time
import os
import sys

GALLOWS = [
    """
       -----
       |   |
           |
           |
           |
           |
    =========""",
    """
       -----
       |   |
       O   |
           |
           |
           |
    =========""",
    """
       -----
       |   |
       O   |
       |   |
           |
           |
    =========""",
    """
       -----
       |   |
       O   |
      /|   |
           |
           |
    =========""",
    """
       -----
       |   |
       O   |
      /|\  |
           |
           |
    =========""",
    """
       -----
       |   |
       O   |
      /|\  |
      /    |
           |
    =========""",
    """
       -----
       |   |
       O   |
      /|\  |
      / \  |
           |
    ========="""
]

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

class HangmanClient:
    def __init__(self, servers):
        self.servers = servers
        self.server_index = 0
        self.player_id = ""
        self.socket = None
        self.running = True
        self.state_cache = None

    def connect(self):
        while self.running:
            server_str = self.servers[self.server_index]
            host, port = server_str.split(':')
            port = int(port)
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect((host, port))
                msg = {"type": "connect", "player_id": self.player_id}
                self.socket.sendall((json.dumps(msg) + "\n").encode('utf-8'))
                
                # Loop until disconnect
                self._receive_loop()
                
            except Exception as e:
                clear_screen()
                print(f"[{server_str}] Indisponível ou Conexão Perdida.")
                print("Tentando conectar ao servidor de backup em 2 segundos...")
                self.socket = None
                self.server_index = (self.server_index + 1) % len(self.servers)
                time.sleep(2)

    def _receive_loop(self):
        buffer = ""
        try:
            while self.running:
                data = self.socket.recv(4096).decode('utf-8')
                if not data:
                    break
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        self.process_message(json.loads(line))
        except Exception:
            pass
        finally:
            if self.socket:
                self.socket.close()
                self.socket = None

    def start_input_loop(self):
        while self.running:
            try:
                guess = input()
                if not guess.strip():
                    continue
                if self.socket and self.state_cache and self.state_cache.get('status') == 'playing':
                    msg = {"type": "guess", "letter": guess.strip()[0]}
                    try:
                        self.socket.sendall((json.dumps(msg) + "\n").encode('utf-8'))
                    except Exception:
                        pass
            except KeyboardInterrupt:
                self.running = False
                if self.socket:
                    self.socket.close()

    def process_message(self, msg):
        msg_type = msg.get('type')
        if msg_type == 'connected':
            self.player_id = msg.get('player_id')
        elif msg_type == 'waiting':
            clear_screen()
            print("--- JOGO DA FORCA DISTRIBUÍDO ---")
            print(f"Servidor Atual: {self.servers[self.server_index]}")
            print(f"Você está na fila de espera. Posição: {msg.get('position')}")
            print("Aguardando um oponente...")
        elif msg_type == 'game_state':
            self.state_cache = msg
            self.draw_ui(msg)

    def draw_ui(self, state):
        clear_screen()
        status = state.get('status')
        wrong_count = state.get('wrong_count', 0)
        
        print("--- JOGO DA FORCA DISTRIBUÍDO: MODO CORRIDA ---")
        print(f"Conectado em: {self.servers[self.server_index]}")
        
        if status == 'won':
            print("\n==================================")
            print("*** PARABÉNS! VOCÊ VENCEU! ***")
            print("==================================")
            print(f"A palavra final era: {state.get('full_word')}")
            print("\nPressione Ctrl+C para sair do jogo.")
            return
        elif status == 'lost':
            print("\n==================================")
            print("*** QUE PENA! VOCÊ PERDEU! ***")
            print("==================================")
            print(f"A palavra resolvida seria: {state.get('full_word')}")
            print(f"O vencedor foi: {state.get('winner')}")
            print("\nPressione Ctrl+C para sair do jogo.")
            return
            
        opp_status = state.get('opponent_status')
        if opp_status:
            if opp_status == 'disconnected':
                print("\n[!] Seu oponente se desconectou. Ele tem 30s para voltar, senão você vence por abandono (W.O).")
            else:
                opp_wrong = state.get('opponent_wrong', 0)
                print(f"\n[OPONENTE] Erros: {opp_wrong}/6 | Status: {state.get('opponent_word_state')}")

        print(GALLOWS[min(wrong_count, 6)])
        print(f"\nSua Palavra:     {state.get('word_state')}")
        print(f"Letras Tentadas: {', '.join(sorted(state.get('guessed', [])))}")
        print(f"Seus Erros:      {wrong_count}/6")
        print("\nSua jogada: Digite uma letra e aperte Enter: ", end="", flush=True)

if __name__ == '__main__':
    servers_arg = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:5000,127.0.0.1:5001"
    servers = servers_arg.split(',')
    
    client = HangmanClient(servers)
    
    t = threading.Thread(target=client.connect, daemon=True)
    t.start()
    
    client.start_input_loop()
