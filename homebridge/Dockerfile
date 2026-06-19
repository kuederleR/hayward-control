FROM homebridge/homebridge:latest

# Install plugins globally and also add them to the storage directory's
# package.json. The HB Supervisor runs npm install on startup looking at
# /homebridge/package.json — listing plugins there ensures the supervisor
# properly installs and maintains them in /homebridge/node_modules/ so
# the -P /var/lib/homebridge/node_modules flag finds them.
# Do NOT set USER homebridge — s6-overlay manages the
# privilege drop internally and needs root for init.
USER root

RUN npm install -g homebridge-http-switch && \
    npm install -g homebridge-advanced-http-temperature-humidity && \
    cd /homebridge && \
    npm init -y && \
    npm install homebridge-http-switch homebridge-advanced-http-temperature-humidity && \
    chown -R 102:105 /home/homebridge /homebridge/node_modules /homebridge/package.json /homebridge/package-lock.json

COPY config.json /homebridge/config.json
RUN chown 102:105 /homebridge/config.json
