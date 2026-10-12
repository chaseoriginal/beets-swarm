# beets-swarm

Music library manager and auto-tagger for Plex-compatible libraries.

## Stack

- **Host**: ore-dock-110-1
- **Stack**: `beets-swarm`
- **Image**: lscr.io/linuxserver/beets:latest
- **Config**: named volume `beets.config`

## Volumes

| Volume | Type | Source | Target |
|--------|------|--------|--------|
| beets.config | named | beets.config | /config |
| music | bind | /media/Multimedia/Music | /music |
| downloads | bind | /media/Multimedia/Incoming | /downloads |

## Ports

| Port | Published | Protocol |
|------|----------|----------|
| 8337 | 8337 | TCP |

## Deploy

```bash
ssh ore-dock-110-1
cd /data/compose/beets-swarm
set -a && source .env && docker stack deploy -c docker-compose.yml --with-registry-auth beets-swarm && set +a
```
