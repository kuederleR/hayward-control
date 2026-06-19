FROM homebridge/homebridge:latest

# Custom HomeBridge plugin that calls our backend API via HTTP.
# Bundled as a local file dependency so it's independent of npm
# registry and survives the HB Supervisor's startup npm install.
USER root

COPY homebridge-plugin /hayward-plugin
RUN chown -R 102:105 /hayward-plugin

RUN cd /homebridge && \
    npm init -y && \
    npm install /hayward-plugin && \
    chown -R 102:105 /home/homebridge /homebridge/node_modules /homebridge/package.json /homebridge/package-lock.json

COPY homebridge/config.json /homebridge/config.json
RUN chown 102:105 /homebridge/config.json
