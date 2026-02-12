1. ~~Correct errors resulting from unescaped markdown~~
2. If possible, configure bot to respond to `@mention command` format in channels/groups
3. Configure `/docker` command to return swarm service staus by default (i.e. "stack name: 7/7 services running) instead of only returning containers running on same node as bot (possibly requires deployment via stack (agents?) instead of standalone container?)
4. Include error alerts and status separately for down/stuck services (i.e. "stack name: 5/7 services running, 2/7 services failed: servicename1, servicename2")
5. ~~Implement fix for container image response returning `N/A`~~
6. Keep current behavior if a node name is specified (i.e. `/docker esquie`)
7. ~~Fix for `/status` command returning "ServiceName: UP" if status is not 2xx/3xx (i.e. "✅ Portainer: UP (404)")~~