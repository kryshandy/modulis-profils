# Commandes du projet. Deux façons de travailler :
#   - dans Docker (recommandé) : make up, make dtest, make dshell…
#   - dans le venv WSL (rapide pour les tests) : make test, make lint…
# Toutes les commandes se lancent depuis WSL Ubuntu, à la racine du projet.

VENV ?= $(HOME)/.venvs/modulis-profils
PY := $(VENV)/bin/python
COMPOSE := docker compose

.PHONY: help venv install lint fmt test cov check migrations migrate run seed-demo up up-force down logs dtest dshell dmanage admin superadmin pages backup backup-list backup-verify restore backup-repo

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

up: ## Docker : démarre web + worker + postgres + redis + sauvegardes (sauvegarde avant reconstruction)
	@if $(COMPOSE) ps --status running --services 2>/dev/null | grep -qx db; then 		echo "→ Sauvegarde de sécurité avant reconstruction…"; 		$(COMPOSE) run --rm --build backup backup.sh manual avant-build >/dev/null || { echo "Sauvegarde impossible : reconstruction annulée (make up-force pour passer outre)"; exit 1; }; 	fi
	$(COMPOSE) up -d --build
	@echo "→ http://localhost:8000   admin : http://localhost:8000/gestion/"

up-force: ## Docker : comme make up, sans la sauvegarde préalable
	$(COMPOSE) up -d --build

down: ## Docker : arrête (les données restent ; ne JAMAIS ajouter -v sans sauvegarde récente)
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

admin: ## Docker : crée un compte de l'équipe (mot de passe, 2FA à la 1re connexion)
	$(COMPOSE) exec web python manage.py create_staff

superadmin: ## Docker : super-admin d'évaluation (mot de passe fixe dans .env) — delete=1 pour le supprimer
	$(COMPOSE) exec web python manage.py bootstrap_superadmin $(if $(delete),--delete,)

pages: ## Docker : parcours de toutes les pages (public, espace pro, admin) et liste des erreurs
	$(COMPOSE) exec -T web python manage.py shell < scripts/check_pages.py

backup: ## Sauvegarde immédiate base + médias vers BACKUP_DIR (hors Docker)
	$(COMPOSE) run --rm backup backup.sh manual $(label)

backup-list: ## Liste les sauvegardes disponibles
	$(COMPOSE) run --rm backup list.sh

backup-verify: ## Restauration test de la dernière sauvegarde (ou name=…) dans une base jetable
	$(COMPOSE) run --rm backup verify.sh $(or $(name),latest)

restore: ## Restaure une sauvegarde (name=latest|2026-11-13_023000) — arrête web/worker pendant l'opération
	@test -n "$(name)" || { echo "Usage : make restore name=latest   (voir make backup-list)"; exit 1; }
	$(COMPOSE) stop web worker
	$(COMPOSE) run --rm backup restore.sh $(name) $(only) --yes
	$(COMPOSE) start web worker
	@echo "→ Restauration terminée. Vérifiez http://localhost:8000"

backup-repo: ## Copie de sauvegarde du dépôt git (bundle) — DEST=/mnt/d/backups
	bash scripts/wsl/backup-repo.sh $(DEST)
