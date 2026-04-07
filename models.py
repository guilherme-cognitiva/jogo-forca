import time
import uuid

class PlayerState:
    def __init__(self, player_id=None):
        self.player_id = player_id or str(uuid.uuid4())
        self.guessed_letters = set()
        self.wrong_count = 0
        self.status = 'waiting' # 'waiting', 'playing', 'won', 'lost', 'disconnected'
        self.disconnect_time = None
        self.opponent_id = None
        self.hint_used = False
        self.word = ''

    def to_dict(self):
        return {
            'player_id': self.player_id,
            'guessed_letters': list(self.guessed_letters),
            'wrong_count': self.wrong_count,
            'status': self.status,
            'disconnect_time': self.disconnect_time,
            'opponent_id': self.opponent_id,
            'hint_used': self.hint_used,
            'word': self.word,
        }

    @classmethod
    def from_dict(cls, data):
        p = cls(data['player_id'])
        p.guessed_letters = set(data['guessed_letters'])
        p.wrong_count = data['wrong_count']
        p.status = data['status']
        p.disconnect_time = data['disconnect_time']
        p.opponent_id = data['opponent_id']
        p.hint_used = data.get('hint_used', False)
        p.word = data.get('word', '')
        return p

class GameState:
    def __init__(self, game_id=None, word="DISTRIBUIDO"):
        self.game_id = game_id or str(uuid.uuid4())
        self.word = word.upper()
        self.players = {} # player_id -> PlayerState
        self.status = 'playing' # 'playing', 'finished'
        self.winner_id = None

    def to_dict(self):
        return {
            'game_id': self.game_id,
            'word': self.word,
            'players': {k: v.to_dict() for k, v in self.players.items()},
            'status': self.status,
            'winner_id': self.winner_id
        }

    @classmethod
    def from_dict(cls, data):
        g = cls(data['game_id'], data['word'])
        g.players = {k: PlayerState.from_dict(v) for k, v in data['players'].items()}
        g.status = data['status']
        g.winner_id = data['winner_id']
        return g
