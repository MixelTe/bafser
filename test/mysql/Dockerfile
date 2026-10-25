FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . .
RUN python -m pip install --no-cache-dir . pyright
CMD ["sh", "-c", "python -m compileall -q src test && python -m unittest discover -s test -v && pyright --project test/typing"]
