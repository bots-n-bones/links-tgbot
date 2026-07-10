.PHONY: dev test migrate lint bot-dev seed

dev:
	docker compose up --build

test:
	pytest

lint:
	ruff check .
	black --check .

migrate:
	alembic -c db/alembic.ini upgrade head

bot-dev:
	bash scripts/run_bot_dev.sh

seed:
	python scripts/seed_fake_data.py
