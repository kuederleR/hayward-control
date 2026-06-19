FROM homebridge/homebridge:latest

# Install plugins into the HomeBridge storage directory so the
# -P /var/lib/homebridge/node_modules flag finds them.
# Do NOT set USER homebridge — s6-overlay manages the
# privilege drop internally and needs root for init.
USER root

RUN npm install -g homebridge-http-switch && \
    npm install -g homebridge-advanced-http-temperature-humidity && \
    mkdir -p /homebridge/node_modules && \
    ln -s /opt/homebridge/lib/node_modules/homebridge-http-switch /homebridge/node_modules/ && \
    ln -s /opt/homebridge/lib/node_modules/homebridge-advanced-http-temperature-humidity /homebridge/node_modules/ && \
    chown -R 102:105 /home/homebridge

COPY config.json /homebridge/config.json
RUN chown 102:105 /homebridge/config.json
