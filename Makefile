# Commandes du projet. Deux façons de travailler :
#   - dans Docker (recommandé) : make up, make dtest, make dshell…
#   - dans le venv WSL (rapide pour les tests) : make test, make lint…
# Toutes les commandes se lancent depuis WSL Ubuntu, à la racine du projet.

VENV ?= $(HOME)/.venvs/modulis-profils
PY := $(VENV)/bin/python
COMPOSE := docker compose

.PHONY: help venv install lint fmt test cov check migrations migrate run seed-demo up down logs dtest dshell dmanage backup-repo

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## Crée le venv WSL et installe les dépendances de dev
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q --upgrade pip
	$(VENV)/bin/pip install -q -r requirements/dev.txt

lint: ## Ruff : erreurs + format (sans modifier)
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

fmt: ## Ruff : corrige et formate
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

test: ## Tests (venv, SQLite)
	$(VENV)/bin/pytest

cov: ## Tests + couverture
	$(VENV)/bin/pytest --cov --cov-report=term-missing

check: lint ## Vérification complète avant commit
	DJANGO_SETTINGS_MODULE=config.settings.test $(PY) manage.py check
	DJANGO_SETTINGS_MODULE=config.settings.test $(PY) manage.py makemigrations --check --dry-run
	$(VENV)/bin/pytest --cov --cov-fail-under=80

migrations: ## Crée les migrations
	$(PY) manage.py makemigrations

migrate: ## Applique les migrations (venv)
	$(PY) manage.py migrate

run: ## Serveur de dev sans Docker (SQLite)
	$(PY) manage.py runserver 0.0.0.0:8000

seed-demo: ## Données de démonstration (profils, lot de cartes)
	$(PY) manage.py seed_demo

up: ## Docker : démarre web + worker + postgres + redis
	$(COMPOSE) up -d --build
	@echo "→ http://localhost:8000   admin : http://localhost:8000/gestion/"

down: ## Docker : arrête
	$(COMPOSE) down

logs: ## Docker : journaux (les SMS de dev s'affichent ici)
	$(COMPOSE) logs -f web worker

dtest: ## Docker : tests sur PostgreSQL
	$(COMPOSE) run --rm -e DJANGO_SETTINGS_MODULE=config.settings.test \
		-e TEST_DATABASE_URL=postgres://modulis:modulis@db:5432/modulis_profils web pytest -p no:cacheprovider --create-db

dshell: ## Docker : shell Django
	$(COMPOSE) exec web python manage.py shell

dmanage: ## Docker : manage.py (ex. make dmanage cmd="createsuperuser")
	$(COMPOSE) exec web python manage.py $(cmd)

backup-repo: ## Copie de sauvegarde du dépôt git (bundle) — DEST=/mnt/d/backups
	bash scripts/wsl/backup-repo.sh $(DEST)
