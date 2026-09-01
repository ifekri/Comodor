"""Discord: the fourth channel.

One token, a websocket the bot opens out to (nothing here needs a public
address), an allow-list of snowflake ids, and a message that can be edited as
the answer arrives. The module is split the way the other channels are:
`api.py` speaks REST, `gateway.py` speaks the websocket protocol, `bot.py`
decides what a message means.
"""
