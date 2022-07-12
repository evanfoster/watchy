FROM pyston/pyston:2.3.4

WORKDIR /app
COPY requirements.txt .
RUN pip install --use-feature=2020-resolver -r requirements.txt
COPY *.py Makefile ./
