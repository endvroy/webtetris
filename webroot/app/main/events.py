import json
from . import lobby
from app.tetrisLogic import tetris_logic
from flask import request
from flask_socketio import join_room, rooms, leave_room
from flask_login import current_user
from .. import socketio

# a match is equavilent to a room

# no conflict exist, no need for lock
# match_id -> RoomInfo
match_rminfo = {}


# tell front end if some player joined or left, player id is not fixed
def player_update(room_info):
    data = {}
    pid = 1
    data['player2'] = 0
    for psid in room_info.players:
        player = room_info.players[psid]
        player_name = 'player' + str(pid)
        data[player_name] = player.username
        pid = pid + 1

    print(data)
    print('room_info.room_id', room_info.room_id)
    socketio.emit('player_update', json.dumps(data), room=room_info.room_id, namespace='/game')
    print('rooms', rooms())


@socketio.on('connect', namespace='/lobby_event')
def on_enter_lobby():
    join_room(0)
    data = lobby.get_room_list()
    socketio.emit('room_list', json.dumps(data), room=0, namespace='/lobby_event')
    lobby.add_to_plist(current_user.username)
    data = lobby.get_plist()
    socketio.emit('player_list', json.dumps(data), room=0, namespace='/lobby_event')


@socketio.on('disconnect', namespace='/lobby_event')
def on_leave_lobby():
    print('leave_lobby')
    lobby.remove_from_plist(current_user.username)
    data = lobby.get_plist()
    socketio.emit('player_list', json.dumps(data), room=0, namespace='/lobby_event')
    leave_room(0)


@socketio.on('join', namespace='/game')
def on_join(data):
    # data = json.loads(data)
    # create new room when
    room_id = data['room']
    crsid = request.sid
    # attemp to join a match
    try:
        lobby.join_match(sid=request.sid, match_id=int(room_id))
    except lobby.JoinFailureError:
        return_data = {}
        return_data['err_msg'] = 'join failed due to some reason'
        socketio.emit('join_failure', json.dumps(return_data), room=request.sid, namespace='/game')
        return
    # join message broadcast room
    join_room(int(room_id))
    # add the player to detail room info, if room info does not exist, create one
    if int(room_id) not in match_rminfo:
        match_rminfo[int(room_id)] = tetris_logic.RoomInfo(int(room_id))
    room_info = match_rminfo[int(room_id)]
    sid = request.sid
    current_player = tetris_logic.Player(sid=sid, username=current_user.username)
    print("current_player.username", current_player.username)
    current_player.opponent = None
    print("room_info.players", room_info.players)
    for psid in room_info.players:
        current_player.opponent = room_info.players[psid]
        room_info.players[psid].opponent = current_player

    room_info.players[sid] = current_player
    print("join", sid)
    player_update(room_info)


def leave_game():
    crsid = request.sid
    username = crsid
    try:
        room_id = lobby.sid_match[username]
        room_info = match_rminfo[int(room_id)]
        lobby.leave_match(crsid)
    except KeyError:
        raise RuntimeError('user {} is not in a game'.format(username))
    # stop game if some players left
    if room_info.game_status is 'on':
        room_info.game[request.sid].stop_game()
    # remove the player from the room
    leave_room(room_id)
    # delete room info if no players left
    if len(room_info.players) is 0:
        del match_rminfo[int(room_id)]
        return
    # otherwise maintain room info and remove the player properly
    if request.sid in room_info.players:
        if room_info.players[request.sid].opponent is not None:
            room_info.players[request.sid].opponent.opponent = None
        del room_info.players[request.sid]
    player_update(room_info)


@socketio.on('disconnect', namespace='/game')
def on_disconnect():
    leave_game()


@socketio.on('chat_msg', namespace='/game')
def chat(data):
    # data = json.loads(data)
    print(data)
    # print(json.loads(data))
    crsid = request.sid
    room_list = rooms()
    print(room_list)
    data['player'] = current_user.username
    print('------', json.dumps(data))
    for room in room_list:
        if room is request.sid:
            continue
        socketio.emit('chat_msg', json.dumps(data), room=room, namespace='/game')


# unfortunatly we get two message in different namespace saying the same thing,
# and this seems the only way to do it, maybe assign the two message with one namespace '/chat' is a better idea, but this takes one additional socket
@socketio.on('chat_msg', namespace='/lobby_event')
def chat_copy(data):
    # data = json.loads(data)
    print(data)
    # print(json.loads(data))
    crsid = request.sid
    room_list = rooms()
    print(room_list)
    data['player'] = current_user.username
    print('------', json.dumps(data))
    for room in room_list:
        if room is request.sid:
            continue
        socketio.emit('chat_msg', json.dumps(data), room=room, namespace='/lobby_event')


def start_game(room_id):
    try:
        room_info = match_rminfo[int(room_id)]
    except KeyError:
        raise RuntimeError('room {} does not exist'.format(room_id))
    game = {}
    # init room
    room_info.game_status = 'on'
    room_info.loser = None
    room_info.game = game
    # start games
    for psid in room_info.players:
        game[psid] = tetris_logic.Tetris(sid=psid, room_info=room_info)
    socketio.emit('game_status', json.dumps({'action': 'start'}), room=room_info.room_id, namespace='/game')


# insecure, require user authentication
@socketio.on('ready', namespace='/game')
def on_ready():
    crsid = request.sid
    print(match_rminfo)
    try:
        room_id = lobby.sid_match[crsid]
        room_info = match_rminfo[int(room_id)]
    except KeyError:
        raise RuntimeError('user {} is not in a room'.format(crsid))
    # block ready message when game is on
    if room_info.game_status is 'on':
        return
    print('request_sid', request.sid)
    print('room_info.players', room_info.players)
    if request.sid in room_info.players:
        player = room_info.players[request.sid]
        player.ready()
        socketio.emit('ready', json.dumps({'status': room_info.players[request.sid].is_ready}), room=request.sid, namespace='/game')
        print(player.is_ready)
        if player.opponent is not None and player.opponent.is_ready:
            start_game(room_id)
    


@socketio.on('operate', namespace='/game')
def operate_game(data):
    # data = json.loads(data)
    crsid = request.sid
    try:
        room_id = lobby.sid_match[crsid]
        room_info = match_rminfo[int(room_id)]
    except KeyError:
        raise RuntimeError('user {} is not in a room'.format(crsid))
    game = room_info.game
    if len(game) and request.sid in game.keys():
        game[request.sid].operate(instruction=data['instruction'])
