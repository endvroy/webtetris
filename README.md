# WebTetris
WebTetris an online 2-player Tetris game. There're 4 pages: sign up, log in, lobby, and game room. In lobby, you can see your personal information and all other spare player's usernames, also a list of all rooms in which game is going or which is waiting for another player. You can join in a room for battle or create a new room by clicking the "+" button. While joining a room, you'll see the information of you and your rival, and how the game is going on both side. Beside, in both lobby and game room, you can enjoy the chatting with all other players, or just with your rival in a room. 


# Run it locally

Install and run `vagrant`. Service will start on `localhost:8080/`. You can play by opening two DIFFERENT browsers, create several different accounts and join the same game room.

# Notes

As suggested in Flask documentation, we choose `eventlet` to serve as websocket transporter and WSGI server.

We apply CSRF token and enough authorization to achieve security. Also, we escape all input to avoid SQL Injection and Cross-Site Scripting. 

`nginx` is used to serve static files and proxy socket connection.

Entering room by URL is allowed, but its legality will be checked.

# Spotlights
## Multiple threads and message queue for sending instructions

In the game, there are multiple sources of operation instructions, move from the player and drop from the timer and perhaps disturbance from other players. and these instructions should be handled properly. If some users are sending massive instructions, perform these instructions should not starve other jobs of the server.
    
We unified the multiple instruction sources with a message deque, with a worker handling messages in the queue.
    
By sending instructions, players (and perhaps other message producers) put their operation at the bottom and timer at the top.
    
The worker is a Tetris game that reads the messages and perform the instructions in a child thread. And time windows are assigned to decrease probability of starvation.
    
In this way, massive player messages will not block other instructions from executing.
    
Besides unifying the sources makes it easier to add more utilities like creating barriers for users easier in the future.

## Message queue in broadcasting

We introduced worker children threads to deal with multiple instruction sources.
    
They will produce the results of instructions and need to send the results to the players, but the socket connection is owned by the parent server thread.
    
To communicate between threads and not to block each other, a message queue service is used to coordinate operations such as broadcasting.

The socket extension we use supports Redis message queue for forwarding broadcasts, and thus we used it to simplify our work.

## Race conditions and resource leaks

The lobby module seems easy, but it is not. The problem is race conditions and resource leaks might occur if we are not careful.
    
To understand why these problems occur and our solutions, we need to be aware there are two connections in our web app: an HTTP connection to get the HTML files, and a websocket connection to received data pushed by the server. the HTTP connection closes once the HTML files are retrieved, but the websocket connection persists until the user leaves this page. Especially, when a user is redirected to another URL, the original websocket connection automatically disconnects, and if the player makes another websocket connection, he would have a different websocket session id.
    
Second, the lobby requires two key data structure to function: a mapping from a websocket’s session id to the match id, and a mapping from the match id to the username of the two players.
    
With these background information, we introduce the three race conditions we have to deal with:
    
- When two players both want to create a new room. We must make sure they are allocated different room id’s.
    
- When two players both want to join the same room with only one seat. We must make sure only one of them succeeds.
    
- When one player wants to join a room, but the player originally in the room leaves it. We must reasonably resolve the problem.  
    
All three race conditions are solved with locks that guards either the next room id or the two key data structures. This is a bit inefficient, of course, as a more efficient solution would be only lock the relevant key-value pairs. But that is almost as hard as implementing a NoSQL database, so we chose a safe solution.

For the resource leaks, consider what happens when a player was in the lobby but now wants to create a room. The data structure to store the room info is not available yet, so we must create it sometime. Then the player needs to be redirected to the new URL. Here is the dilemma: If you create the room before the player is redirected, but the player is not redirected to the URL for some reason, the player would not make any websocket connection to our server, therefore he would never disconnect from our server since he never connected. If the player never disconnects, we would never have a chance to remove the room structure from our memory. If we do not create the room structure before the player is redirect, he would have no URL to be redirected to.

Our solution to this dilemma is to only allocate the room id when the user asks to create a new room. We send the room id back to the frontend, then the browser redirects to the URL specified by the room id. On the server side, if the player did get the new URL and made a websocket connection there, we create a new room structure in our memory. Because the websocket connection is established, we know when to free the resource.

We thought of many other solutions but they all fail to this scenario or to the nature of websocket connections. The current implementation seems straightforward but is actually carefully selected. The general principle is to not allocate anything in our server before the new websocket connection is established, because the only way we know when to deallocate the resource is when the websocket connection is closed, since we cannot know when a user leaves the page from anything else. This is our solution to the resource leak problem.
