![Lucie LLM Queue Header](assets/readme_header.webp)



# Introduction
Ce projet implémente un système de gestion de file d'attente intelligent pour contrôler l'accès à Lucie, notre modèle de langage (LLM) entraîné from scratch. Face à l'intérêt croissant pour les modèles de langage open source et la nécessité de gérer efficacement les ressources de calcul, ce système permet d'offrir une expérience utilisateur optimale tout en maintenant la stabilité du service.

### Le Contexte
Lucie est déployée via une interface basée sur open web-ui, permettant au public de tester et d'interagir avec le modèle. Cependant, pour garantir des performances optimales et une expérience utilisateur de qualité, nous devons limiter le nombre d'accès simultanés tout en assurant une distribution équitable du temps d'utilisation.

### Pourquoi un système de file d'attente ?
- **Gestion des ressources** : Optimise l'utilisation des ressources GPU/CPU nécessaires pour faire fonctionner le modèle
- **Équité d'accès** : Assure une distribution équitable du temps d'accès entre les utilisateurs
- **Expérience utilisateur** : Offre une visibilité claire sur le temps d'attente et la disponibilité
- **Stabilité** : Évite la surcharge du système en contrôlant le nombre d'utilisateurs simultanés

### Les Caractéristiques 
- Gestion de 50 sessions utilisateurs simultanées
- Sessions limitées à 20 minutes pour maximiser le nombre d'utilisateurs servis
- Système de "draft" de 5 minutes permettant une transition fluide entre les utilisateurs
- Mécanisme de file d'attente transparent avec notifications en temps réel
- Intégration seamless avec l'interface open web-ui

### Dernier build -TEST- :

<details>
<summary>Cliquez pour déplier/replier</summary>

#### TEST RESULT

1. **Mode test-only **
```
{output}
```
Votre contenu ici (laissez une ligne vide après le summary)
- Point 1
- Point 2
- Point 3

</details>

## Table des matières
- 1. [Introduction](#introduction)
-   - [1.1. Le Contexte](#le-contexte)  
-   - [1.2. Pourquoi un système de file d'attente ?](#pourquoi-un-système-de-file-dattente)
-   - [1.3. Les Caractéristiques](#les-caractéristiques)
- 2. [Fonctionnalités](#fonctionnalités)
- 3. [Architecture](#architecture)
-   - [3.1. Prérequis](#prérequis)
-   - [3.2. Installation](#installation)
-   - [3.3. Configuration](#configuration)
- 4. [Installation](#installation)
- 5. [Configuration](#configuration)
- 6. [Utilisation](#utilisation)
- 7. [Scripts CLI](#scripts-cli)
- 8. [Tests](#tests)
- 9. [Structure du Projet](#structure-du-projet)
- 10. [API Reference](#api-reference)
- 11. [Glossaire](#glossaire)

## Fonctionnalités
- 🔄 File d'attente en temps réel
- 👥 Gestion de 50 utilisateurs simultanés
- ⏲️ Sessions de 20 minutes
- 🎟️ Système de réservation temporaire (draft)
- 📊 Métriques en temps réel
- 🔔 Notifications via Redis Pub/Sub

# Architecture
- **FastAPI** : APIrest et Websocket
- **Redis** : Cache et pub/sub
- **Celery** : Gestion des tâches asynchrones
- **Docker** : Service management

### Prérequis
- Python 3.12+
- Docker et Docker Compose
- Poetry



<details>
<summary> <h2 id="installation"> Installation</h2></summary>

<div style="margin-left: 20px; padding: 10px; border-left: 2px solid #3eaf7c;">


### Installation avec Poetry

#### Installation des dépendances
```bash
poetry install
```
#### Activation de l'environnement virtuel
```bash
poetry shell
```

###  Docker compose
#### Lancement de tous les services
```bash
docker-compose up -d
```
#### Arrêt des services
```bash
docker-compose down
```
</div>
</details>

<details>
<summary> <h2 id="configuration"> Configuration</h2></summary>

<div style="margin-left: 20px; padding: 10px; border-left: 2px solid #3eaf7c;">

### Variables d'environnement

#### Redis Configuration
```Yaml
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
```

### Application Configuration
```yaml
MAX_ACTIVE_USERS=50
SESSION_DURATION=1200 # 20 minutes
DRAFT_DURATION=300 # 5 minutes
```

</div>
</details>

# Utilisation

<details>
<summary> <h2 id="modedev"> Démarrage en mode dev</h2></summary>

<div style="margin-left: 20px; padding: 10px; border-left: 2px solid #3eaf7c;">


### Lancement auto reload pour traquer les changements
```bash
poetry run dev run --reload
```

### Lancement sur un port spécifique
```bash
poetry run dev run --port 8080
```

### Démarrage en production

## Avec Docker Compose
```bash
docker-compose up -d
```
## Vérification des logs
```bash
docker-compose logs -f
```

</div>
</details>

<details>
<summary> <h2 id="scriptscli">Scripts CLI</h2></summary>

<div style="margin-left: 20px; padding: 10px; border-left: 2px solid #3eaf7c;">

### Script de développement (`poetry run dev`)

#### Lancer l'application
```bash
dev run [--host] [--port] [--reload]
```
#### Gérer Docker
```bash
dev docker-up # Démarre les services
```
```bash
dev docker-down # Stop services
```
```bash
dev docker-logs # Affiche les logs
```

### Script de test (`poetry run test`)
#### Lancer les tests
```bash
test run [--cov] [--html] [test_path]
```
#### Tests dans Docker
```bash
test docker [--logs] [--test-only]
```

#### Exemples de sortie

1. **Mode test-only**
```
============================= test session starts ==============================
platform linux -- Python 3.9.19, pytest-7.4.4, pluggy-1.5.0
rootdir: /app
plugins: asyncio-0.21.2, anyio-3.7.1, cov-4.1.0
collected 7 items

tests/test_api_endpoints.py::TestAPI::test_join_queue_flow_with_available_slots PASSED
tests/test_api_endpoints.py::TestAPI::test_join_queue_flow_when_full PASSED
tests/test_integration.py::TestIntegration::test_concurrent_users PASSED
tests/test_integration.py::TestIntegration::test_requeue_mechanism PASSED
tests/test_queue_manager.py::TestQueueManager::test_add_to_queue PASSED
tests/test_queue_manager.py::TestQueueManager::test_draft_flow PASSED
tests/test_queue_manager.py::TestQueueManager::test_draft_expiration PASSED

---------- coverage: platform linux, python 3.9.19-final-0 -----------
Name                   Stmts   Miss  Cover
------------------------------------------
app/main.py               30      5    83%
app/queue_manager.py      82      8    90%
------------------------------------------
TOTAL                    112     13    88%

============================== 7 passed in 0.40s ==============================
```

#### Options de test
| Option | Description |
|--------|-------------|
| `--logs` | Affiche les logs détaillés des tests |
| `--test-only` | Affiche uniquement les résultats des tests (sans logs Docker) |
| `--cov` | Active la couverture de code |
| `--html` | Génère un rapport HTML de couverture |

### Script de formatage (`poetry run format`)
#### option de formatage
| option | description |
|--------|-------------|
| format black [--check] | Formatage avec black |
| format isort | Tri des imports |
| format lint | Vérification avec flake8 |
| format all | Exécute tous les formatages |


</div>
</details>





### Script de test de charge (`poetry run load-test`)
#### Test utilisateur unique
```bash
load-test single USER_ID
```
#### Test de groupe
```bash
load-test group --size 50
```
#### Test de charge progressif
```bash
load-test load --users 200 --batch-size 20 --delay 5
```


## Tests

### Types de tests
- **Tests unitaires** : Teste les composants individuellement
- **Tests d'intégration** : Vérifie l'interaction entre les composants
- **Tests API** : Valide les endpoints HTTP
- **Tests de charge** : Évalue les performances sous charge

### Exécution des tests
#### Tous les tests
```bash
poetry run test run
```
#### Avec couverture
```bash
poetry run test run --cov --html
```
#### Tests dans Docker
```bash
poetry run test docker
```


## API Reference

### Endpoints REST FastAPI
| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/queue/join/{user_id}` | POST | Rejoindre la file d'attente |
| `/queue/confirm/{user_id}` | POST | Confirmer la connexion |
| `/queue/leave/{user_id}` | POST | Quitter la file |
| `/queue/status/{user_id}` | GET | Obtenir le statut |
| `/queue/metrics` | GET | Obtenir les métriques |


### États utilisateur
- **Waiting** : En attente dans la file (position > 0)
- **Draft** : Slot disponible et temporairement réservé (5 minutes pour confirmer)
- **Connected** : Session active (20 minutes)
- **Disconnected** : Déconnecté du système

### Transitions d'états
1. `Waiting → Draft` : Quand un slot devient disponible
2. `Draft → Connected` : Après confirmation dans les 5 minutes
3. `Draft → Waiting` : Si pas de confirmation dans les 5 minutes (retour en file)
4. `Connected → Disconnected` : Après 20 minutes ou déconnexion manuelle

### Notifications Redis
| Canal | Description | Exemple de message |
|-------|-------------|-------------------|
| `queue_status:{user_id}` | En attente | ```{"status": "waiting", "position": 5}``` |
| `queue_status:{user_id}` | Slot disponible | ```{"status": "draft", "duration": 300}``` |
| `queue_status:{user_id}` | Connexion confirmée | ```{"status": "connected", "session_duration": 1200}``` |
| `queue_status:{user_id}` | Session expirée | ```{"status": "disconnected", "reason": "session_timeout"}``` |
| `queue_status:{user_id}` | Draft expiré | ```{"status": "waiting", "reason": "draft_timeout", "position": 5}``` |

### Exemples de scénarios de notification

1. **Utilisateur rejoint la file**
```json
{
    "user_id": "user123",
    "status": "waiting",
    "position": 5,
    "estimated_wait": 600
}
```

2. **Slot devient disponible**
```json
{
    "user_id": "user123",
    "status": "slot_available",
    "duration": 300,
    "expires_at": "2024-01-20T15:30:00Z"
}
```

3. **Connexion confirmée**
```json
{
    "user_id": "user123",
    "status": "connected",
    "session_duration": 1200,
    "expires_at": "2024-01-20T16:00:00Z"
}
```

4. **Notification d'expiration imminente**
```json
{
    "user_id": "user123",
    "status": "expiring_soon",
    "remaining_time": 60,
    "session_type": "active"
}
```

5. **Notification de déconnexion**
```json
{
    "user_id": "user123",
    "status": "disconnected",
    "reason": "session_timeout",
    "requeue_position": 3
}
```

## Notions

### On dit les termes :
- **Slot** -> Place disponible pour un utilisateur actif dans le système
- **Draft** -> Période de réservation temporaire (5 minutes) pendant laquelle un utilisateur peut confirmer sa connexion
- **Session** -> Durée de connexion active (20 minutes) pendant laquelle un utilisateur peut utiliser le système
- **File d'attente** -> Liste ordonnée des utilisateurs en attente d'un slot
- **Pub/Sub** -> Système de publication/souscription de Redis permettant la communication en temps réel, c'est mieux que le websocket quand la communication est unidirectionnel (notification)

## Installation avec Make

Le projet utilise un Makefile pour automatiser l'installation et la configuration de l'environnement de développement.

### Commandes Make disponibles

| Commande | Description |
|----------|-------------|
| `make setup` | Installation complète (pyenv, Python 3.12, Poetry, dépendances) |
| `make install-pyenv` | Installation de pyenv |
| `make install-python` | Installation de Python 3.12.1 via pyenv |
| `make install-poetry` | Installation de Poetry |
| `make install-deps` | Installation des dépendances du projet |
| `make dev` | Démarrage du serveur de développement |
| `make test` | Exécution des tests |
| `make docker-up` | Démarrage des services Docker |
| `make docker-down` | Arrêt des services Docker |
| `make clean` | Nettoyage des fichiers temporaires et caches |

### Installation initiale

1. **Installation complète automatique** :
```bash
make setup
source ~/.bashrc  
```

2. **Installation étape par étape** :
```bash
# Installation de pyenv
make install-pyenv
source ~/.bashrc 

# Installation de Python 3.12
make install-python

# Installation de Poetry
make install-poetry

# Installation des dépendances
make install-deps
```

### Développement

```bash
# Démarrer le serveur de développement
make dev

# Lancer les tests
make test

# Démarrer les services Docker
make docker-up

# Arrêter les services Docker
make docker-down
```

### Nettoyage

```bash
# Nettoyer les fichiers temporaires et caches
make clean
```

Pour voir toutes les commandes disponibles :
```bash
make help
```

