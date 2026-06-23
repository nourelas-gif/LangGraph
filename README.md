# LAB22 - Agentic AI Robust Wikipedia Agent

## Objectif

Créer un agent robuste qui :
1. reçoit une question utilisateur ;
2. prépare le prompt ;
3. interroge Wikipedia ;
4. route automatiquement :
   - vers la réponse standard si Wikipedia répond correctement ;
   - vers une DLQ si Wikipedia renvoie 404, 503, timeout, JSON invalide ou contenu vide ;
5. vérifie automatiquement la conformité avec pytest ;
6. exécute les tests à chaque mise à jour avec GitHub Actions.

## Architecture

```text
Chat Input
  ↓
Prompt Node
  ↓
Wikipedia API Tool
  ↓
Smart Router
  ├── Succès : réponse contrôlée → Chat Output
  └── Échec : API Request POST DLQ → Chat Output de secours
```

## Installation locale

```bash
python -m venv .venv
source .venv/Scripts/activate   # Git Bash Windows
pip install -r requirements.txt
```

## Exécuter les tests

```bash
pytest -q
```

## Lancer l'API locale

```bash
uvicorn app:app --reload --port 7860
```

Puis :

```bash
curl -X POST http://127.0.0.1:7860/api/v1/run/S5_J22_AGENT   -H "Content-Type: application/json"   -d "{"input_value":"Where Morocco is located ?"}"
```

## Mocks utilisés

La bibliothèque `responses` intercepte les appels HTTP de `requests`.

Mocks principaux :
- `GET https://en.wikipedia.org/w/api.php` :
  - succès 200 ;
  - erreurs 404, 429, 500, 503 ;
  - timeout ;
  - connection error ;
  - JSON invalide ;
  - page absente ;
  - extract vide.
- `POST http://127.0.0.1:3000/dlq/messages` :
  - succès 201/202 ;
  - panne DLQ simulée.

## GitHub Actions

Le fichier `.github/workflows/ci-agent.yml` installe Python, installe les dépendances puis exécute :

```bash
pytest -q --cov=src --cov-report=term-missing
```

## Badge README

Après le premier push GitHub, ajoutez en haut du README :

```markdown
![Agentic AI Tests](https://github.com/VotreUtilisateur/VotreDepot/actions/workflows/ci-agent.yml/badge.svg)
```
