# Disposable stateless acceptance only; the existing pharmacy Dockerfile is unchanged.
FROM python:3.12-alpine
WORKDIR /srv/site
COPY site/ /srv/site/
USER 65534:65534
EXPOSE 8080
CMD ["python", "-m", "http.server", "8080", "--bind", "0.0.0.0"]
