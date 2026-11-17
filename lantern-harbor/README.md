# Lantern Harbor

A property-trading board game for 2–6 players, set in a harbor town at night. Play on one shared screen, or online with everyone on their own computer or phone.

**Play:** https://sgnoohc.github.io/monet/lantern-harbor/

- Roll two dice and sail clockwise around 40 spaces. Buy streets, transit lines and works, and charge rent to whoever lands on them.
- Unbought property goes to auction (optional). Doubles roll again; three in a row sends you to the Brig.
- Full color sets double the rent and allow houses, built evenly, then an inn.
- Mortgage for half the price; lifting it costs that plus 10%.
- Trade streets, cash and Brig pardons with anyone. A trade to another person asks you to hand them the screen.
- Two card decks: **Tide** cards mostly move you, **Guild** cards mostly pay or charge you.
- Computer players can take any seat. They buy, bid, build, raise cash when in debt, and make trade offers.
- Options: starting cash, auctions, a Calm Waters pot for taxes and fines, and computer speed.
- The game in progress is kept in the browser's local storage, so a refresh picks up where you left off.

Prices, rents, building costs and card effects follow the standard US edition of the classic property game. The streets, card wording, colors and board design are this game's own.

## Playing online

Choose **Online** in the setup screen. One person creates a room and sends the five-letter code or the invite link (`…/lantern-harbor/#CODE`). Everyone else joins from their own device.

- The room's creator adds computer players, sets the options and starts the game. If they leave, the next connected player takes over those controls.
- A chat box sits beside the board, and in the lobby.
- If someone drops out, anyone can hand their seat to the computer. They can take it back when they return, or a newcomer can take the empty seat.
- Refreshing the page rejoins the same room and seat.

Rooms live in the Realtime Database of the `spaceattack-88bd3` Firebase project, under `lanternHarbor/rooms/<CODE>`. The rules in `../spaceattack/database.rules.json` let anyone who knows a room code read and write that room, and nothing else. Changes to that file only take effect once they're published in the Firebase console (Realtime Database → Rules).

Each change to a game is written as the whole game state with a revision number, inside a transaction, so two screens can never both apply a move. The screen that owns the acting seat applies the move. Computer seats are run by the first connected human player's screen.

The Claude-hosted copy of this page can't reach Firebase, so it offers single-screen play only and points to the GitHub copy for online games.

## Code

Everything is in `index.html`. The `<script id="engine">` block is the rules engine and the computer players, with no DOM access. The second script is the interface.

    node lantern-harbor/test/sim.js

plays 400 computer-only games against the engine (2–6 players, every option combination) and checks money, ownership, buildings and the card decks after every step.
