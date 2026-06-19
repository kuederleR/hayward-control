FROM homebridge/homebridge:latest

# Install plugins into the HomeBridge storage directory so the
# -P /var/lib/homebridge/node_modules flag finds them.
# Do NOT set USER homebridge — s6-overlay manages the
# privilege drop internally and needs root for init.
USER root

RUN npm install --no-save --prefix /homebridge \
        homebridge-http-switch \
        homebridge-http-temperature-humidity \
    && chown -R 102:105 /home/homebridge

COPY config.json /homebridge/config.json
RUN chown 102:105 /homebridge/config.json
