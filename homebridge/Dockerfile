FROM homebridge/homebridge:latest

# Install plugins into the HomeBridge storage directory so the
# -P /var/lib/homebridge/node_modules flag finds them.
# Do NOT set USER homebridge — s6-overlay manages the
# privilege drop internally and needs root for init.
USER root

RUN npm install -g homebridge-http-switch && \
    npm install -g homebridge-advanced-http-temperature-humidity && \
    mkdir -p /homebridge/node_modules && \
    for pkg in homebridge-http-switch homebridge-advanced-http-temperature-humidity; do \
        src="$(npm root -g)/$pkg"; \
        if [ -d "$$src" ]; then \
            ln -s "$$src" "/homebridge/node_modules/$pkg"; \
        else \
            echo "ERROR: $pkg not found at $$src" >&2; exit 1; \
        fi; \
    done && \
    chown -R 102:105 /home/homebridge

COPY config.json /homebridge/config.json
RUN chown 102:105 /homebridge/config.json
