from flask import Flask, render_template
from flask_socketio import SocketIO, emit
from flask import request as flask_request
import threading
import time
import uuid
import logging
import argparse

from models import GameState, PlayerState
import game_engine
from p2p_sync import P2PManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.config['SECRET_KEY'] = 'hangman-web-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

state_lock = threading.Lock()
games = {}              # game_id -> GameState
waiting_queue = []      # list of player_ids
sid_to_player = {}      # socket sid -> player_id
player_to_sid = {}      # player_id -> socket sid
last_updated = [0.0]    # mutable container for timestamp

p2p_manager = None      # set in main() when peers are configured


# ---------------------------------------------------------------------------
# P2P sync
# ---------------------------------------------------------------------------

def _sync_state():
    """Broadcast current state to P2P peers. Must be called WITH state_lock held."""
    if p2p_manager is None:
        return
    last_updated[0] = time.time()
    state_dict = {
        'last_updated': last_updated[0],
        'games': {k: v.to_dict() for k, v in games.items()},
        'waiting_queue': list(waiting_queue),
    }
    p2p_manager.broadcast_state(state_dict)


def on_p2p_state_received(state_dict):
    """Called by P2PManager when a peer sends us its state."""
    with state_lock:
        remote_time = state_dict.get('last_updated', 0)
        if remote_time <= last_updated[0]:
            return  # We already have a newer state

        last_updated[0] = remote_time
        games.clear()
        games.update({k: GameState.from_dict(v) for k, v in state_dict.get('games', {}).items()})
        waiting_queue.clear()
        waiting_queue.extend(state_dict.get('waiting_queue', []))
        logging.info("Estado sincronizado via P2P.")

        # Notify every locally connected client with updated state
        for player_id, sid in list(player_to_sid.items()):
            if player_id in waiting_queue:
                pos = waiting_queue.index(player_id) + 1
                socketio.emit('waiting', {'position': pos}, to=sid)
            else:
                for game in games.values():
                    if player_id in game.players:
                        _emit_game_state(player_id, game, sid)
                        break


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_game_state_msg(game, player_id):
    player = game.players[player_id]
    msg = {
        'status': player.status,
        'word_state': game_engine.get_masked_word(game.word, player.guessed_letters),
        'wrong_count': player.wrong_count,
        'guessed': sorted(list(player.guessed_letters)),
    }
    if player.opponent_id:
        opponent = game.players.get(player.opponent_id)
        if opponent:
            msg['opponent_wrong'] = opponent.wrong_count
            msg['opponent_status'] = opponent.status
            msg['opponent_word_state'] = game_engine.get_masked_word(game.word, opponent.guessed_letters)
            msg['opponent_guessed'] = sorted(list(opponent.guessed_letters))
            if game.status == 'finished' or player.status in ['won', 'lost']:
                msg['full_word'] = game.word
                msg['winner_id'] = game.winner_id
    msg['hint_used'] = player.hint_used
    return msg


def _emit_game_state(player_id, game, sid=None):
    sid = sid or player_to_sid.get(player_id)
    if sid:
        socketio.emit('game_state', _build_game_state_msg(game, player_id), to=sid)


def notify_all_in_game(game):
    for player_id in game.players:
        _emit_game_state(player_id, game)


def check_matchmaking():
    """Must be called WITH state_lock held."""
    while len(waiting_queue) >= 2:
        p1_id = waiting_queue.pop(0)
        p2_id = waiting_queue.pop(0)
        new_game = game_engine.create_game(p1_id, p2_id)
        games[new_game.game_id] = new_game
        logging.info(f"Match criado: {p1_id[:8]} vs {p2_id[:8]}")
        notify_all_in_game(new_game)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


# ---------------------------------------------------------------------------
# Socket.IO events
# ---------------------------------------------------------------------------

@socketio.on('connect')
def on_connect():
    sid = flask_request.sid
    # Client sends its stored player_id (from localStorage) for reconnection
    player_id = flask_request.args.get('player_id') or str(uuid.uuid4())

    with state_lock:
        sid_to_player[sid] = player_id
        player_to_sid[player_id] = sid

        # Check if this player is reconnecting to an active game
        reconnected = False
        for game in games.values():
            if player_id in game.players:
                player = game.players[player_id]
                if player.status == 'disconnected':
                    # Restore them to the game
                    player.status = 'playing'
                    player.disconnect_time = None
                    logging.info(f"Jogador {player_id[:8]} reconectou ao jogo.")
                    _sync_state()
                reconnected = True
                emit('connected', {'player_id': player_id})
                _emit_game_state(player_id, game, sid)
                break

        if not reconnected:
            if player_id not in waiting_queue:
                waiting_queue.append(player_id)
            pos = waiting_queue.index(player_id) + 1
            emit('connected', {'player_id': player_id})
            emit('waiting', {'position': pos})
            check_matchmaking()
            _sync_state()


@socketio.on('disconnect')
def on_disconnect():
    sid = flask_request.sid
    with state_lock:
        player_id = sid_to_player.pop(sid, None)
        if not player_id:
            return
        player_to_sid.pop(player_id, None)

        if player_id in waiting_queue:
            waiting_queue.remove(player_id)
            _sync_state()
            return

        for game in games.values():
            if player_id in game.players:
                player = game.players[player_id]
                if player.status == 'playing':
                    player.status = 'disconnected'
                    player.disconnect_time = time.time()
                    logging.info(f"Jogador {player_id[:8]} desconectou.")
                    notify_all_in_game(game)
                    _sync_state()
                break


@socketio.on('hint')
def on_hint():
    sid = flask_request.sid
    with state_lock:
        player_id = sid_to_player.get(sid)
        if not player_id:
            return
        for game in games.values():
            if player_id in game.players:
                if game_engine.process_hint(game, player_id):
                    notify_all_in_game(game)
                    _sync_state()
                break


@socketio.on('guess')
def on_guess(data):
    sid = flask_request.sid
    with state_lock:
        player_id = sid_to_player.get(sid)
        if not player_id:
            return
        letter = str(data.get('letter', '')).strip()
        if not letter:
            return
        for game in games.values():
            if player_id in game.players:
                if game_engine.process_guess(game, player_id, letter):
                    notify_all_in_game(game)
                    _sync_state()
                break


# ---------------------------------------------------------------------------
# Background threads
# ---------------------------------------------------------------------------

def _timeout_checker():
    while True:
        time.sleep(5)
        with state_lock:
            for game in list(games.values()):
                if game_engine.check_disconnect_timeouts(game, timeout_seconds=30):
                    notify_all_in_game(game)
                    _sync_state()


threading.Thread(target=_timeout_checker, daemon=True).start()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Jogo da Forca - Servidor Web")
    parser.add_argument('--port', type=int, default=5000, help="Porta HTTP para os clientes")
    parser.add_argument('--sync-port', type=int, default=6000, help="Porta P2P para sync entre servidores")
    parser.add_argument('--peers', type=str, default="",
                        help="Lista de peers separados por virgula: host:sync_port (ex: 1.2.3.4:6000)")
    args = parser.parse_args()

    peer_list = []
    if args.peers:
        for entry in args.peers.split(','):
            h, p = entry.strip().split(':')
            peer_list.append((h, int(p)))

    if peer_list:
        p2p_manager = P2PManager('0.0.0.0', args.sync_port, peer_list)
        p2p_manager.set_callback(on_p2p_state_received)
        logging.info(f"P2P sync ativo na porta {args.sync_port} | peers: {peer_list}")
    else:
        logging.info("Modo single-server (sem peers P2P configurados)")

    logging.info(f"Servidor web em http://0.0.0.0:{args.port}")
    socketio.run(app, host='0.0.0.0', port=args.port, debug=False, allow_unsafe_werkzeug=True)
