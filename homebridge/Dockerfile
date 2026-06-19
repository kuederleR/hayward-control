FROM homebridge/homebridge:latest

# Install plugins and fix npm cache ownership so the
# homebridge (UID 102) user can run npm install at startup.
# Do NOT set USER homebridge — s6-overlay manages the
# privilege drop internally and needs root for init.
USER root

RUN npm install -g \
        homebridge-http-switch \
        homebridge-http-temperature-humidity \
    && chown -R 102:105 /home/homebridge

COPY config.json /homebridge/config.json
RUN chown 102:105 /homebridge/config.json
