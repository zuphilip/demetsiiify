FROM python:3.5

ADD . /code
WORKDIR /code

RUN\
    pip install -U pip wheel &&\
    pip install -r requirements.txt
