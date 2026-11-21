<p align="center"><img src="docs/kimsufi-logo.png" alt="Kimsufi Watcher" width="120"></p>

<h1 align="center">Kimsufi watcher</h1>

<p align="center">
  Surveille les disponibilités des serveurs Kimsufi / OVH Eco et envoie des alertes Discord.
</p>
<p align="center">
  <img src="docs/screenshot.png" alt="Disponibilités en direct" width="800">
</p>
<p align="center">
  <img src="docs/screenshot-reglages.png" alt="Règles de surveillance et réglages" width="800">
</p>

## [1.0.1] - 2026-11-21

### Modifié
- README : instructions d'installation.
- 
## Fonctionnalités

- Disponibilités en direct par datacenter
- Prix TTC/mois, frais d'installation HT et total du 1er mois TTC
- Règles de surveillance (plan, RAM, stockage)
- Alertes Discord (avec mention @everyone en option)
- Historique des alertes
- Interface web protégée par mot de passe

## Installation (Docker)

```bash
git clone https://github.com/bouba89/kimsufi-watcher.git
cd kimsufi-watcher
cp .env.example .env     # puis édite .env et définis KW_PASS
docker compose up -d --build
```

Puis ouvre `http://127.0.0.1:8080`. Par défaut, l'interface n'écoute que sur
localhost (`KW_BIND=127.0.0.1`) ; pour y accéder depuis un autre poste,
utilise un reverse proxy ou règle `KW_BIND=0.0.0.0` dans `.env`.

## Configuration

| Variable | Rôle | Défaut |
|---|---|---|
| `KW_USER` | Identifiant de l'interface | `admin` |
| `KW_PASS` | Mot de passe de l'interface (**obligatoire**, à définir dans `.env`) | – |
| `KW_BIND` | Adresse d'écoute publiée par Docker | `127.0.0.1` |
| `KW_PORT` | Port publié sur la machine | `8080` |
| `KW_DATA` | Dossier de stockage (config, historique) | dossier de l'app |


### Règles de surveillance

Une alerte Discord part quand le `planCode` correspond et que la RAM et le stockage
**contiennent** le texte indiqué (vide = tout). Exemples : `ram-32g`, `x4000`.
Les noms techniques apparaissent en survolant une config dans la liste.

Le webhook Discord, l'intervalle et les règles se règlent dans l'interface.

> Lance gunicorn avec **un seul worker** (`-w 1`), sinon le thread de surveillance est dupliqué et les alertes arrivent en double.

## Avertissement

Projet indépendant, non affilié à OVHcloud. Kimsufi et OVHcloud sont des marques de leurs propriétaires.
Les prix proviennent du catalogue public OVH et peuvent différer de la 



commande finale.

## Licence

[MIT](LICENSE)
