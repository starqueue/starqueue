### StarQueue database backed message queue for Python 

StarQueue is a message queue server written in Python.

It is desined to be a more simple copy of Amazon Simple Queue Server.

Clients access it via HTTP.  The API is documented at https://github.com/starqueue/starqueue/tree/main/starqueueserver/website

The database is Postgres.

When I developed it initially, I included seamless support for Postgres, MySQL and Microsoft SQL server.  

At some point in the development I gave up on all databases except Postgres, though I have left the MySQL and SQL server code in place.

I deployed StarQueue as an online service at one point (no longer online).  This github repo is a copy of the source code for that service.

This project is not live and is archived, but I have posted it here in case anyone finds it interesting.

andrew.stuart@supercoders.com.au




