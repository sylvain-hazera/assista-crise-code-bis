# security — outillage de sécurité de l'hôte

Outils qui protègent la **machine** hébergeant la plateforme, pas l'application elle-même
(sécurité applicative : [DOCUMENTATION.md](../DOCUMENTATION.md), § 10).

## `ssh-log-shipper/`

Petite image qui recopie les journaux SSH de l'hôte dans un fichier texte, pour que
**fail2ban** puisse bannir les adresses qui tentent de deviner des mots de passe SSH.

**Pourquoi** : la machine Debian n'a pas de `/var/log/auth.log` (journaux uniquement dans
journald), et l'image fail2ban ne sait pas lire journald directement. Ce conteneur exécute
`journalctl -u ssh -f` en root et ajoute chaque ligne à `/logs/ssh.log`, au format syslog
classique : le filtre `sshd` standard de fail2ban fonctionne alors sans modification.

```
journald (hôte) ──► ssh-log-shipper ──► /logs/ssh.log (volume partagé) ──► fail2ban ──► bannissement
```

Ce service ne figure pas dans les fichiers Compose du dépôt : il est déployé à la main sur la
machine de production, avec fail2ban. Il a besoin de lire le journal de l'hôte et de partager
le volume `/logs` avec fail2ban ; exemple à adapter :

```bash
docker build -t assista-crise/ssh-log-shipper security/ssh-log-shipper/
docker run -d --name ssh-log-shipper --restart unless-stopped \
  -v /var/log/journal:/var/log/journal:ro -v /etc/machine-id:/etc/machine-id:ro \
  -v fail2ban_logs:/logs assista-crise/ssh-log-shipper
```

Côté fail2ban, la prison `sshd` pointe alors `logpath = /logs/ssh.log`.

Vérifier que la chaîne fonctionne : `docker exec ssh-log-shipper tail /logs/ssh.log` après une
connexion SSH, puis `fail2ban-client status sshd` dans le conteneur fail2ban.
