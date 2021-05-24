.PHONY: build setup run clean
NAMESPACE?="default"
SECRET_COUNT?="5000"
WATCH_COUNT?="50"

default: run

build:
	docker build -t evanfoster/secret-watchy:latest .
	docker push evanfoster/secret-watchy:latest

setup:
	python3 -m venv venv
	( \
		source venv/bin/activate; \
		pip install -r requirements.txt; \
	)
	echo "Run source venv/bin/activate"

create-secrets:
	python spew.py -n $(NAMESPACE) $(SECRET_COUNT)

run:
	python watchy.py $(WATCH_COUNT)

