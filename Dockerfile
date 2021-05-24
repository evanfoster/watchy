FROM python:3.9-buster

WORKDIR /app
RUN mkdir pyston-src && \
    cd pyston-src && \
    curl -L https://github.com/pyston/pyston/releases/download/pyston_2.2/pyston_2.2_portable.tar.gz | tar -xvz && \
    ./pyston -m venv ../venv && \
    cd ..
COPY requirements.txt .
RUN venv/bin/pip install --use-feature=2020-resolver -r requirements.txt
COPY *.py Makefile ./

ENV VIRTUAL_ENV=/app/venv \
    PATH=/app/venv/bin:/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

