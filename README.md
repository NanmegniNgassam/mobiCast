# MobiCast

Application web pour l'équipe commerciale de Studelecta.  
Analyse les flux de mobilité étudiante africaine vers l'Europe, visualise les corrélations, prédictions et classements par pays de destination.

---

## Prérequis

- [Docker](https://docs.docker.com/get-docker/) ≥ 24
- [Docker Compose](https://docs.docker.com/compose/) v2 (inclus avec Docker Desktop)

---

## Démarrage en 3 commandes

```bash
# 1. Cloner le dépôt
git clone <url-du-depot> mobiCast && cd mobiCast

# 2. Placer les fichiers de référence dans data/defaults/
#    (voir section "Fichiers de référence" ci-dessous)

# 3. Lancer l'application
docker compose up --build
```

L'application est accessible sur **http://localhost:8050**.

---

## Identifiants par défaut

| Champ       | Valeur  |
|-------------|---------|
| Utilisateur | `admin` |
| Mot de passe | `admin` |

> Changez le mot de passe après la première connexion via un accès direct à la base SQLite, ou ajoutez une page d'administration dans une prochaine version.

---

## Fichiers de référence

Deux fichiers de référence doivent être placés dans `data/defaults/` **avant** de lancer Docker.  
Ils sont montés en lecture seule dans le conteneur et utilisés comme sources par défaut quand l'utilisateur ne fournit pas ses propres fichiers.

### 1. Données OECD (bourses)

- **Nom attendu** : `oecd_scholarships.csv` (insensible à la casse)
- **Source** : portail OECD Statistics → *Aid at a Glance* → export CSV
- **Colonne clé** : `donor` (pays donateur / destination), `time_period`, `obs_value`

### 2. Matrice Erasmus+ (mobilité KA1)

- **Nom attendu** : `ErasmusPlus_KA1_*.xlsx` (un ou plusieurs fichiers)
- **Source** : [portail Erasmus+](https://erasmus-plus.ec.europa.eu/resources-and-tools/statistics-and-factsheets) → export KA1 Higher Education
- **Colonnes clés** : coordinator country, participant country

> L'application démarre avec une erreur explicite si l'un de ces fichiers est absent.

---

## Sources de données pour une analyse

Lors du lancement d'une analyse, l'utilisateur fournit :

| Source | Obligatoire | Format | Origine |
|--------|-------------|--------|---------|
| **UNESCO** | Oui | CSV | [UNESCO Institute for Statistics](https://uis.unesco.org/en/uis-student-flow) → indicateur 26420 |
| **OECD** | Non | CSV | Portail OECD Statistics (fichier de référence utilisé si non fourni) |
| **Erasmus+** | Non | XLSX | Portail Erasmus+ KA1 (matrice de référence utilisée si non fourni) |

---

## Persistence des données

Les données survivent à `docker compose down` grâce aux volumes nommés :

| Volume | Contenu |
|--------|---------|
| `mobicast_db` | Base SQLite (`mobicast.db`) |
| `mobicast_data` | Analyses sauvegardées et résultats JSON |

Pour réinitialiser complètement (supprime toutes les analyses) :

```bash
docker compose down -v
```

---

## Variables d'environnement

| Variable | Défaut | Description |
|----------|--------|-------------|
| `SECRET_KEY` | `change-me-in-production` | Clé secrète Flask (à changer en production) |
| `DATABASE_PATH` | `/app/db/mobicast.db` | Chemin vers la base SQLite |
| `DATA_DIR` | `/app/data` | Répertoire racine des données |
| `DEBUG` | `false` | Active les logs verbeux et le mode debug Dash |

Définissez `SECRET_KEY` dans `docker-compose.yml` ou via un fichier `.env` :

```bash
SECRET_KEY=une-cle-aleatoire-longue docker compose up
```
