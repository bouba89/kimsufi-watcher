# Kimsufi Watcher

Surveille la disponibilité des serveurs dédiés **OVHcloud Eco / Kimsufi** et vous prévient sur **Discord** dès qu'une configuration que vous attendez est en stock. Une petite interface web permet de régler la surveillance sans toucher au code.

> Projet non officiel, sans lien avec OVHcloud ni Kimsufi. Les disponibilités et les prix affichés sont indicatifs : vérifiez toujours sur le site au moment de commander.

<!-- Ajoutez ici une capture d'écran : ![Interface](docs/screenshot.png) -->

## Fonctionnalités

- **Alertes Discord** par webhook, avec le nom du serveur, la config, le datacenter, le délai de livraison et le prix.
- **Règles de surveillance** : un serveur (`planCode`) et, au choix, un filtre sur la RAM et sur le stockage. Plusieurs règles possibles, chacune activable ou désactivable.
- **Tableau en direct** de toutes les configs des serveurs surveillés, avec noms commerciaux (KS-LE-3, KS-4…), villes de datacenters et libellés lisibles.
- **Prix** HT et TTC par config, frais d'installation en infobulle.
- **Pas de fausses alertes** : les variantes que l'API annonce mais qu'OVH ne vend pas, et les états `unknown`, ne déclenchent rien.
- **Historique** des dernières alertes.
- **Anti-doublon** : une alerte par config et par datacenter, réarmée quand le stock disparaît.
- Authentification HTTP Basic, déploiement Docker en un seul conteneur.

## Démarrage rapide (Docker)

```bash
git clone https://github.com/<votre-utilisateur>/kimsufi-watcher.git
cd kimsufi-watcher
cp .env.example .env
nano .env                    # définissez KW_USER et KW_PASS
docker compose up -d --build
```

Ouvrez ensuite `http://localhost:8080`, puis :

1. Connectez-vous avec `KW_USER` / `KW_PASS`.
2. Dans **Réglages**, collez l'URL de votre webhook Discord, enregistrez, puis cliquez sur **Envoyer un message de test**.
3. Dans **Règles de surveillance**, ajoutez les serveurs à surveiller et cliquez sur **Enregistrer**.

> Si votre mot de passe contient un `$`, mettez-le entre apostrophes dans `.env` (`KW_PASS='ab$cd'`), sinon Docker Compose l'interprète comme une variable.

### Mise à jour

```bash
git pull
docker compose up -d --build
```

La configuration et l'historique sont conservés dans `./data`.

## Configuration

### Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `KW_USER` | `admin` | Identifiant de l'interface |
| `KW_PASS` | `changeme` hors Docker, **obligatoire** avec `docker compose` | Mot de passe de l'interface |
| `KW_PORT` | `8080` | Port publié par `docker-compose.yml` |
| `KW_DATA` | dossier du script (`/data` dans l'image Docker) | Dossier de `config.json` et `history.json` |

### Réglages (dans l'interface)

| Réglage | Détail |
|---|---|
| Webhook Discord | Jamais renvoyé à la page ; il ne change que si vous en saisissez un nouveau |
| Intervalle | 30 s par défaut, entre 10 s et 3600 s |
| `@everyone` | Mention optionnelle dans l'alerte |

### Règles de surveillance

Une règle contient trois champs :

| Champ | Fonctionnement |
|---|---|
| `planCode` | Identifiant exact du serveur (par exemple `27skle03-v1`) |
| RAM contient | Texte recherché dans le nom technique de la RAM (vide = toutes) |
| Stockage contient | Texte recherché dans le nom technique du stockage (vide = tous) |

Les filtres portent sur les **noms techniques**, que vous voyez en survolant une config dans le tableau : `ram-32g-ddr4-ecc-2666`, `softraid-3x4000sa`, `hybridsoftraid-2x8000sa-2x480ssd`…

Exemples (les `planCode` évoluent avec le catalogue OVH, vérifiez-les) :

| Objectif | planCode | RAM | Stockage |
|---|---|---|---|
| KS-LE-3, 32 Go, toutes configs | `27skle03-v1` | `ram-32g` | *(vide)* |
| KS-LE-3, disques de 4 To | `27skle03-v1` | `ram-32g` | `x4000` |
| KS-4, 2 × 2 To | `24sk40-v1` | *(vide)* | `2x2000` |

**Astuce** : ajoutez d'abord une règle avec le seul `planCode`, enregistrez, et regardez le tableau pour voir les configs qui existent et leurs noms exacts, puis affinez les filtres.

#### Trouver un `planCode`

Le champ `planCode` propose les serveurs vus par l'API. Sinon, avec le catalogue public :

```bash
curl -s "https://eu.api.ovh.com/v1/order/catalog/public/eco?ovhSubsidiary=FR" | python3 -c "
import json,sys
for p in json.load(sys.stdin)['plans']:
    print(p['planCode'], '|', p.get('invoiceName'))"
```

## Comment ça marche

1. Un thread en arrière-plan interroge l'API publique `GET /v1/dedicated/server/datacenter/availabilities` d'OVH à chaque intervalle (sans authentification).
2. Le catalogue `GET /v1/order/catalog/public/eco?ovhSubsidiary=FR` est chargé au démarrage puis toutes les 6 h : noms commerciaux, prix et options réellement vendues.
3. Pour chaque règle active, l'appli compare les configs reçues, ignore les variantes non commandables et envoie une alerte pour chaque nouvelle disponibilité.

### États de disponibilité

| Valeur de l'API | Affichage | Alerte |
|---|---|---|
| `unavailable` | pastille grise | non |
| `unknown` | pastille orange « état inconnu » (OVH ne confirme pas de stock) | non |
| `1H`, `1H-low`, `72H`… | pastille verte avec le délai de livraison (`-low` = stock faible) | oui |

### Exemple d'alerte

```
@everyone KS-LE-3 DISPONIBLE !
32 Go DDR4 ECC 2666 MHz · 3 × 4 To HDD · SoftRAID
Gravelines (France) : livraison sous 1 h (stock faible)
21,99 € HT/mois · 26,39 € TTC
https://eco.ovhcloud.com
```

### Prix

Les prix viennent du catalogue de la filiale française (HT). Le TTC est calculé avec 20 % de TVA (constante `TVA` dans `app.py`). Le total d'une config est la somme du serveur, de l'option RAM et de l'option stockage ; si le tarif d'une option est introuvable, le prix est affiché « dès … ».

## HTTPS avec un reverse proxy (Nginx Proxy Manager, NPMplus…)

L'authentification Basic n'est pas chiffrée : n'exposez jamais l'interface sur Internet sans HTTPS. Avec un proxy qui tourne dans Docker, mettez l'appli sur son réseau et ne publiez aucun port :

```yaml
services:
  kimsufi-watcher:
    build: .
    container_name: kimsufi-watcher
    restart: unless-stopped
    environment:
      KW_USER: ${KW_USER:-admin}
      KW_PASS: ${KW_PASS:?définissez KW_PASS dans .env}
    volumes:
      - ./data:/data
      - /etc/localtime:/etc/localtime:ro
    networks:
      - npm-proxy        # nom du réseau de votre proxy

networks:
  npm-proxy:
    external: true
```

Dans le proxy, créez un hôte avec : **Scheme** `http`, **Forward Hostname** `kimsufi-watcher`, **Forward Port** `8080` (le port interne), puis activez le certificat SSL et **Force HTTPS**.

## Sécurité

- Changez `KW_PASS` : l'interface contient votre webhook et pilote vos règles.
- Ne commitez jamais `.env` ni `data/` (le `.gitignore` les exclut). `data/config.json` contient l'URL du webhook.
- Gardez **un seul worker** gunicorn (`-w 1`), sinon le thread de surveillance est dupliqué et les alertes arrivent en double.
- Un webhook Discord diffusé par erreur doit être supprimé et recréé.

## Dépannage

| Symptôme | Piste |
|---|---|
| Aucune alerte | Les règles ne sont prises en compte qu'après **Enregistrer**. Vérifiez que la config apparaît en vert et « surveillé » dans le tableau. |
| Alertes pour la mauvaise config | Un filtre vide ou trop large : survolez la ligne pour lire le nom technique et affinez. |
| Heure décalée d'une heure | Montez `/etc/localtime` en lecture seule (déjà fait dans `docker-compose.yml`). |
| `401` en boucle | Respectez la casse de `KW_USER` et vérifiez la valeur lue par le conteneur : `docker exec kimsufi-watcher env \| grep KW_`. |
| `502 Bad Gateway` derrière un proxy | Le proxy doit viser `kimsufi-watcher:8080` (port interne) sur le même réseau Docker. |
| Pas de prix ni de noms | Le catalogue n'est pas chargé : consultez l'erreur affichée en haut de la page, la tentative est renouvelée toutes les 10 minutes. |

## Développement (sans Docker)

```bash
pip install -r requirements.txt
KW_PASS=motdepasse python app.py          # http://localhost:8080
# ou
KW_PASS=motdepasse gunicorn -w 1 --threads 4 -b 0.0.0.0:8080 app:app
```

Le projet tient dans un seul fichier, `app.py` (surveillance, API JSON et page web intégrée).

## Limites connues

- L'état des alertes est gardé en mémoire : après un redémarrage, les configs déjà disponibles déclenchent une nouvelle alerte.
- La filiale française (`ovhSubsidiary=FR`) est codée en dur.
- Un code de datacenter inconnu s'affiche en majuscules (`DC_NAMES` dans `app.py`).
- L'API de disponibilité d'OVH n'est pas documentée comme un service garanti : son format peut changer.

## Idées

- Filtre par datacenter dans chaque règle
- Message « plus disponible » avec la durée du stock
- Alerte si l'API OVH ne répond plus
- Préparation automatique du panier avec lien de paiement

## Licence

À définir avant publication (par exemple MIT).
