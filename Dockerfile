FROM python:alpine3.6

RUN apk update \
  && apk add --virtual build-deps gcc python3-dev musl-dev \
  && mkdir /app

ADD . /app/

WORKDIR /app

RUN pip install pipenv \
  && pipenv install --ignore-pipfile --system

CMD [ "./run.sh" ]
