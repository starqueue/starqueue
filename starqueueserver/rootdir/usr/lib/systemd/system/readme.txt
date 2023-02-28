
# AS 10 Jun 2021

Solved a major problem where caddy could not see the unix domain socket.

This was caused by the following settings in caddy's systemd service file:

#PrivateTmp=true
ProtectSystem=full

The solution, as shown above is to comment out PrivateTmp=true and as shown below, add:

ReadWritePaths=/tmp
