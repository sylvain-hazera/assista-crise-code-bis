FROM debian:trixie-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends systemd \
    && rm -rf /var/lib/apt/lists/*
CMD ["sh", "-c", "journalctl -u ssh -f -n 0 -o short --no-pager >> /logs/ssh.log"]
