# Lantern Harbor

A property-trading board game for 2–6 players sharing one screen, set in a harbor town at night.

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

## Code

Everything is in `index.html`. The `<script id="engine">` block is the rules engine and the computer players, with no DOM access. The second script is the interface.

    node lantern-harbor/test/sim.js

plays 400 computer-only games against the engine (2–6 players, every option combination) and checks money, ownership, buildings and the card decks after every step.
