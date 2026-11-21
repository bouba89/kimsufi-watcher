# Changelog

Toutes les évolutions notables de ce projet sont consignées ici.
Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versionnement [SemVer](https://semver.org/lang/fr/).

## [Non publié]

## [1.0.1] - 2026-11-21

### Modifié
- README : instructions d'installation.

## [1.0.0] - 2026-11-20

Première version publiée : interface web, règles multiples, alertes Discord, déploiement Docker.

### Ajouté
- Interface web Flask protégée par authentification HTTP Basic : tableau des disponibilités en direct, règles de surveillance, réglages, historique des alertes et bouton d'envoi d'un message de test.
- Règles multiples : `planCode` + filtre sur la RAM + filtre sur le stockage, chacune activable ou désactivable.
- Alertes Discord par webhook, mention `@everyone` optionnelle, anti-doublon par config et par datacenter (réarmé quand le stock disparaît).
- Noms commerciaux (KS-LE-3, KS-4…) lus dans le catalogue OVH, rafraîchi toutes les 6 h.
- Libellés lisibles : datacenters en ville et pays, RAM (`32 Go DDR4 ECC 2666 MHz`), stockage (`3 × 4 To HDD · SoftRAID`), délais de livraison (`livraison sous 1 h (stock faible)`).
- Prix HT et TTC par config (serveur + option RAM + option stockage), frais d'installation en infobulle, mention « dès » quand le tarif d'une option est introuvable.
- Pastille orange « état inconnu » pour les configs dont OVH ne confirme pas le stock.
- Configuration et historique persistants (`config.json`, `history.json`), dossier réglable avec `KW_DATA`.
- Déploiement Docker : `Dockerfile`, `docker-compose.yml`, `.env.example`, gunicorn avec un seul worker.
- Documentation : README, exemple de configuration derrière un reverse proxy.

### Modifié
- L'intervalle de vérification se règle dans l'interface (10 s minimum, 30 s par défaut).
- Les horodatages utilisent l'heure du serveur (montage de `/etc/localtime` dans le conteneur).

### Corrigé
- Fausses alertes pour des variantes listées par l'API de disponibilité mais absentes des options vendues (par exemple le KS-LE-3 en 64 Go) : elles sont désormais ignorées et grisées.
- Les états `unknown` ne déclenchent plus d'alerte.
- Le filtre porte maintenant sur la RAM et le stockage ; le prototype ne filtrait que le stockage.

### Sécurité
- L'URL du webhook n'est jamais renvoyée à la page et ne change que si une nouvelle valeur est saisie.
- Les données affichées dans l'interface sont échappées.
- Les identifiants sont comparés en temps constant.
- Aucun mot de passe dans le dépôt : `KW_PASS` est obligatoire avec `docker compose` et lu depuis `.env`, ignoré par git.
- Le port n'est publié que sur `127.0.0.1` par défaut (`KW_BIND`).
- Le fichier de configuration est créé avec des droits restreints (`600`).

## [0.1.0] - 2026-11-19

Prototype.

### Ajouté
- Script Python unique qui interroge l'API de disponibilité d'OVH toutes les 30 s et envoie une alerte Discord.
- Filtre sur le `planCode` et le stockage.
- Exécution en service systemd.

[Non publié]: https://github.com/bouba89/kimsufi-watcher/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/bouba89/kimsufi-watcher/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/bouba89/kimsufi-watcher/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/bouba89/kimsufi-watcher/releases/tag/v0.1.0
