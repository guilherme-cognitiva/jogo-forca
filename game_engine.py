import random
import time
from models import GameState, PlayerState

MAX_ERRORS = 6

WORDS = [
    # Tecnologia
    {"word": "COMPUTADOR",  "theme": "Tecnologia"},
    {"word": "ALGORITMO",   "theme": "Tecnologia"},
    {"word": "PROCESSADOR", "theme": "Tecnologia"},
    {"word": "TECLADO",     "theme": "Tecnologia"},
    {"word": "MONITOR",     "theme": "Tecnologia"},
    {"word": "SOFTWARE",    "theme": "Tecnologia"},
    {"word": "SERVIDOR",    "theme": "Tecnologia"},
    {"word": "PROGRAMADOR", "theme": "Tecnologia"},
    {"word": "INTERNET",    "theme": "Tecnologia"},
    {"word": "BLUETOOTH",   "theme": "Tecnologia"},
    # Animais
    {"word": "ELEFANTE",    "theme": "Animal"},
    {"word": "CACHORRO",    "theme": "Animal"},
    {"word": "BORBOLETA",   "theme": "Animal"},
    {"word": "JACARE",      "theme": "Animal"},
    {"word": "PAPAGAIO",    "theme": "Animal"},
    {"word": "TARTARUGA",   "theme": "Animal"},
    {"word": "LEOPARDO",    "theme": "Animal"},
    {"word": "PINGUIM",     "theme": "Animal"},
    {"word": "GIRAFA",      "theme": "Animal"},
    {"word": "CAMELO",      "theme": "Animal"},
    # Esportes
    {"word": "FUTEBOL",     "theme": "Esporte"},
    {"word": "BASQUETE",    "theme": "Esporte"},
    {"word": "VOLEIBOL",    "theme": "Esporte"},
    {"word": "ATLETISMO",   "theme": "Esporte"},
    {"word": "HANDEBOL",    "theme": "Esporte"},
    {"word": "CICLISMO",    "theme": "Esporte"},
    {"word": "NATACAO",     "theme": "Esporte"},
    {"word": "GINASTICA",   "theme": "Esporte"},
    # Paises
    {"word": "ARGENTINA",   "theme": "Pais"},
    {"word": "PORTUGAL",    "theme": "Pais"},
    {"word": "ALEMANHA",    "theme": "Pais"},
    {"word": "AUSTRALIA",   "theme": "Pais"},
    {"word": "COLOMBIA",    "theme": "Pais"},
    {"word": "NORUEGA",     "theme": "Pais"},
    {"word": "DINAMARCA",   "theme": "Pais"},
    {"word": "INDONESIA",   "theme": "Pais"},
    # Alimentos
    {"word": "CHOCOLATE",   "theme": "Alimento"},
    {"word": "ABACAXI",     "theme": "Alimento"},
    {"word": "MORANGO",     "theme": "Alimento"},
    {"word": "BRIGADEIRO",  "theme": "Alimento"},
    {"word": "SORVETE",     "theme": "Alimento"},
    {"word": "CARAMELO",    "theme": "Alimento"},
    {"word": "PIPOCA",      "theme": "Alimento"},
    {"word": "MACARRAO",    "theme": "Alimento"},
    # Profissoes
    {"word": "ENGENHEIRO",  "theme": "Profissao"},
    {"word": "ARQUITETO",   "theme": "Profissao"},
    {"word": "ADVOGADO",    "theme": "Profissao"},
    {"word": "PROFESSOR",   "theme": "Profissao"},
    {"word": "ASTRONAUTA",  "theme": "Profissao"},
    {"word": "BOMBEIRO",    "theme": "Profissao"},
    {"word": "PILOTO",      "theme": "Profissao"},
    {"word": "VETERINARIO", "theme": "Profissao"},
]

def create_game(player1_id: str, player2_id: str) -> GameState:
    # Garante que cada jogador recebe uma palavra de categoria diferente
    themes = list(set(w["theme"] for w in WORDS))
    selected_themes = random.sample(themes, 2)
    word1 = random.choice([w for w in WORDS if w["theme"] == selected_themes[0]])
    word2 = random.choice([w for w in WORDS if w["theme"] == selected_themes[1]])

    game = GameState()

    p1 = PlayerState(player1_id)
    p2 = PlayerState(player2_id)

    p1.word  = word1["word"]
    p1.theme = word1["theme"]
    p2.word  = word2["word"]
    p2.theme = word2["theme"]

    p1.opponent_id = player2_id
    p2.opponent_id = player1_id

    p1.status = 'playing'
    p2.status = 'playing'

    game.players[player1_id] = p1
    game.players[player2_id] = p2

    return game

def is_word_guessed(word: str, guessed_letters: set) -> bool:
    return all(char in guessed_letters for char in word)

def process_guess(game_state: GameState, player_id: str, letter: str) -> bool:
    """Returns True if state changed, False otherwise."""
    if game_state.status != 'playing':
        return False
        
    player = game_state.players.get(player_id)
    if not player or player.status != 'playing':
        return False

    letter = letter.upper()
    if not letter.isalpha() or len(letter) != 1:
        return False

    if letter in player.guessed_letters:
        return False

    player.guessed_letters.add(letter)

    if letter not in player.word:
        player.wrong_count += 1

    # Check for win/loss
    if player.wrong_count >= MAX_ERRORS:
        player.status = 'lost'
        if player.opponent_id:
            opponent = game_state.players.get(player.opponent_id)
            if opponent and opponent.status == 'playing':
                opponent.status = 'won'
                game_state.winner_id = opponent.player_id
        game_state.status = 'finished'
    elif is_word_guessed(player.word, player.guessed_letters):
        player.status = 'won'
        game_state.winner_id = player.player_id
        game_state.status = 'finished'
        if player.opponent_id:
            opponent = game_state.players.get(player.opponent_id)
            if opponent and opponent.status == 'playing':
                opponent.status = 'lost'

    return True

def get_masked_word(word: str, guessed_letters: set) -> str:
    return " ".join([char if char in guessed_letters else "_" for char in word])

def process_hint(game_state: GameState, player_id: str) -> bool:
    """Reveals one random unguessed letter from the word. Returns True if state changed."""
    if game_state.status != 'playing':
        return False
    player = game_state.players.get(player_id)
    if not player or player.status != 'playing' or player.hint_used:
        return False

    unguessed = [c for c in set(player.word) if c not in player.guessed_letters]
    if not unguessed:
        return False

    player.hint_used = True
    letter = random.choice(unguessed)
    process_guess(game_state, player_id, letter)
    return True

def check_disconnect_timeouts(game_state: GameState, timeout_seconds=30):
    """
    Checks if a disconnected player has timed out. 
    If so, they lose and their opponent wins.
    Returns True if state changed.
    """
    if game_state.status != 'playing':
        return False

    changed = False
    now = time.time()
    
    for player_id, player in game_state.players.items():
        if player.status == 'disconnected' and player.disconnect_time:
            if now - player.disconnect_time > timeout_seconds:
                # Player timed out!
                player.status = 'lost'
                if player.opponent_id:
                    opponent = game_state.players.get(player.opponent_id)
                    if opponent and (opponent.status == 'playing' or opponent.status == 'waiting'):
                        opponent.status = 'won'
                        game_state.winner_id = opponent.player_id
                game_state.status = 'finished'
                changed = True

    return changed
