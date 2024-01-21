FROM python:3.10-slim-buster

# Create app directory
WORKDIR /usr/src/app

# Install app dependencies
COPY requirements.txt ./

RUN pip install -r requirements.txt

ADD app.py ./

CMD ["python3", "-m" , "flask", "run", "--host=0.0.0.0"]