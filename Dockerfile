FROM python:alpine3.6

EXPOSE 8889
RUN apk update \
  && apk add --virtual build-essential gcc python3-dev musl-dev \
  && apk add --virtual build-deps \
  && mkdir /app

ADD . /app/

WORKDIR /app

RUN pip install -r requirements.txt \
  && pip install .

CMD [ "./run.sh" ]
