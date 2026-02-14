1. ~~Correct errors resulting from unescaped markdown~~
2. ~~If possible, configure bot to respond to `@mention command` format in channels/groups~~
3. ~~Configure `/docker` command to return swarm service staus by default (i.e. "stack name: 7/7 services running) instead of only returning containers running on same node as bot (possibly requires deployment via stack (agents?) instead of standalone container?)~~
4. ~~Include error alerts and status separately for down/stuck services (i.e. "stack name: 5/7 services running, 2/7 services failed: servicename1, servicename2")~~
5. ~~Implement fix for container image response returning `N/A`~~
6. ~~Keep current behavior if a node name is specified (i.e. `/docker esquie`)~~
7. ~~Fix for `/status` command returning "ServiceName: UP" if status is not 2xx/3xx (i.e. "✅ Portainer: UP (404)")~~
8. ~~If no host is specified for `/ping` command, reply "Pong" for self status report.~~
9. ~~Implement webhook functionality to receive alerts from services without native Telegram integration, including an environment variable for Telegram chat ID (default fallback to direct message to authorized user IDs)~~
10. ~~Correct command logic for `/docker` regarding "global" services - current logic assumes that the number of replicas should == the number of ready nodes, but various placement constraints could render this untrue and cause false errors.~~
11. Implement Proxmox functionality: get cluster/node/guest status/information, control VMs/containers
12. ~~Implement Portainer functionality: stack listing and control (start/stop)~~ — container management and creation TBD