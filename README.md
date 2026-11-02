# Chauffage 4HEAT – suivi et journal des réglages

Application Django pour affiner la régulation du chauffage :

- **Statut** : état en cours, températures, O₂, derniers défauts, derniers réglages.
- **Graphes** : chaudière / fumées / O₂ / état sur 3 panneaux alignés dans le temps, défauts en bandes rouges, changements de réglages en traits verticaux.
- **Démarrages** : tous les démarrages superposés et alignés sur leur début, pour voir l'effet d'un réglage d'un démarrage à l'autre.
- **Défauts** : épisodes par code, durée médiane, délai après le démarrage.
- **Réglages** : saisie d'un changement (utilisable au téléphone devant le chauffage), horodaté, avec l'ancienne valeur retrouvée automatiquement.
- **Alertes Telegram** : message quand un défaut (code ≠ 0) est confirmé sur 2 mesures consécutives, et quand il disparaît.

Le **collecteur** (`fourheat_logger/`, service `collector`) interroge le module 4HEAT et ajoute une ligne à `4heat_log.csv`.
L'app et les alertes lisent ce CSV en lecture seule. Le journal des réglages (≈ 289 paramètres) est dans une base SQLite.

## Démarrage (Docker)

```bash
cp .env.example .env        # puis édite .env : HEATING_CSV_DIR (dossier du CSV), FOURHEAT_HOST (IP du module)
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

Ouvre `http://IP-DE-LA-VM:8000` (port modifiable avec `WEB_PORT`).

### Collecteur

Le service `collector` démarre avec le reste. Il n'envoie au module que la requête de lecture `["SEL","0"]`.
Module joignable : une ligne toutes les 60 s ; injoignable : test toutes les 2 min, rien n'est écrit.

```bash
docker compose logs -f collector     # « module reachable », « boiler running: recording »...
```

**Passer de l'ancien service systemd au conteneur** (une seule fois, sur la VM) :

```bash
sudo systemctl disable --now fourheat-logger            # sinon le module est interrogé deux fois
sudo cp /var/lib/fourheat/4heat_log.csv "$HEATING_CSV_DIR"/   # garde l'historique (même format)
docker compose up -d --build
```

Si le CSV existant a un autre en-tête, le collecteur refuse d'y écrire : il s'arrête (code 2), Docker le relance en boucle sans toucher au fichier, et `docker compose logs collector` le dit.

**Filtre « chaudière au repos »** : dans `fourheat_logger/config.py`, `REST_STATES` est vide (tout est enregistré tant que le module répond). Une fois la valeur au repos connue, par ex. `frozenset({0})`, puis `docker compose up -d --build`.

### Importer ton classeur Excel

```bash
docker compose cp /chemin/Liste_Parametres2.xlsx web:/tmp/params.xlsx
docker compose exec web python manage.py import_excel /tmp/params.xlsx --dry-run   # contrôle sans rien écrire
docker compose exec web python manage.py import_excel /tmp/params.xlsx
```

L'import crée les paramètres (avec leur section et leur valeur de base) et les changements datés.
Il peut être relancé sans doublon. Les colonnes **sans date** du classeur ne peuvent pas être placées dans le temps :
la commande les liste, à toi de les saisir dans « Réglages » avec une date approximative (dans l'ordre affiché).
Les dates venant du classeur sont marquées « ≈ » (seul le jour est connu).

Ensuite, dans l'admin (`/admin/`) : ajoute les **libellés de codes** (nom des états et des défauts) et les descriptions de paramètres. Ils s'affichent à la place des numéros.

### Alertes Telegram

1. Crée un bot avec @BotFather → tu obtiens le token. Écris un message au bot, puis ouvre `https://api.telegram.org/bot<TOKEN>/getUpdates` pour lire ton `chat.id`.
2. Mets `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` dans `.env` (jamais dans le code ni dans git).
3. `docker compose up -d --build` (le service `telegram-com` démarre avec les autres ; sans token il s'arrête en erreur).

Test : `docker compose run --rm telegram-com python manage.py run_alerts --once`.
Si Telegram est injoignable, l'état n'est pas enregistré : le message est renvoyé au passage suivant.

Commande **/status** : le bot répond avec la dernière mesure (heure, état, défaut, températures, O₂).
Seul le chat `TELEGRAM_CHAT_ID` reçoit une réponse ; les commandes envoyées pendant que le service était arrêté sont ignorées.
Optionnel : dans @BotFather, `/setcommands` → `status - Dernière mesure` pour l'avoir dans le menu.

## Sécurité

- Compte obligatoire sur toutes les pages (et l'app peut **écrire** le journal) : n'expose pas le port sur Internet. Accès externe via VPN (WireGuard / Tailscale), pas de redirection de port.
- Derrière un reverse proxy en https : renseigne `CSRF_TRUSTED_ORIGINS` (ex. `https://chauffage.example`) et restreins `ALLOWED_HOSTS`.

## Sauvegarde

Le dossier `./db` contient le journal des réglages et les comptes : c'est la **seule copie**. Sauvegarde-le (copie du fichier `db.sqlite3`, de préférence app arrêtée ou avec `sqlite3 db.sqlite3 ".backup copie.sqlite3"`). Le CSV reste la source des mesures.

## Base de données et GitLab

SQLite suffit (un seul utilisateur, quelques centaines de lignes). Si tu veux une vraie base, crée une base **dédiée** et passe `DATABASE_URL=postgres://user:mdp@hote:5432/chauffage`. Je déconseille de réutiliser le PostgreSQL embarqué de GitLab (il est géré par GitLab, mises à jour et sauvegardes comprises). Le chemin PostgreSQL n'a pas été testé.

## Définitions utilisées

- **Démarrage** : première mesure après une pause d'au moins 30 min dans le CSV (réglable sur la page Démarrages).
- **Épisode de défaut** : suite de mesures avec le même code ≠ 0 ; coupé si le CSV a un trou de plus de 10 min.
- **Trou** dans les graphes : plus de 5 min sans mesure, la courbe n'est pas reliée.
- La page Statut ne peut pas distinguer « chauffage éteint » de « collecteur arrêté » (le collecteur n'écrit rien quand le module ne répond pas).
- Dates et heures : heure locale (Europe/Zurich), sans fuseau, comme le CSV. Lors du passage à l'heure d'hiver, l'heure 02:00–03:00 est ambiguë.

## Tests

```bash
pip install -r requirements.txt
python manage.py test monitor                                   # tout (Django + logique)
python3 -m unittest discover -s monitor/tests -t . -p "test_core_*.py"   # logique seule (sans Django)
```

Si `MigrationTests` échoue après une modification de `models.py` : `python manage.py makemigrations monitor`.

## Où est quoi

| Fichier | Rôle |
|---|---|
| `fourheat_logger/` | collecteur : lecture du module 4HEAT, écriture du CSV (copie de `../fourheat_logger`, plus un correctif dans `storage.py` : une ligne n'est plus collée à une dernière ligne sans retour à la ligne) |
| `monitor/core/readings.py` | lecture du CSV, démarrages, épisodes de défauts |
| `monitor/core/alerts.py` | logique d'alerte + envoi Telegram |
| `monitor/core/charts.py` | construction des graphes (Plotly.js) |
| `monitor/core/excel_import.py` | lecture du classeur Excel |
| `monitor/core/journal.py` | valeur en vigueur / valeur précédente d'un paramètre |
| `monitor/models.py`, `forms.py`, `admin.py` | journal, saisie, administration |
| `monitor/views.py`, `urls.py`, `templates/` | pages |
| `monitor/management/commands/` | `import_excel`, `run_alerts` |
| `config/settings.py` | réglages, pilotés par variables d'environnement |
