FROM python:3.9

WORKDIR /code

RUN mkdir -p /code/vo/images

RUN mkdir -p /code/records

COPY ./requirements.txt /code/

RUN pip install -r requirements.txt

COPY ./vo /code/vo

# Добавляем src в PYTHONPATH
ENV PYTHONPATH=/code/vo

# Запускаем как модуль
CMD ["python", "-m", "vo"]
