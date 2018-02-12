FROM python:alpine3.6

EXPOSE 8889
RUN apk update \
  && apk add --virtual build-deps gcc python3-dev musl-dev \
  && mkdir /app

ADD . /app/

WORKDIR /app

RUN pip install -r requirements.txt

CMD [ "./run.sh" ]
