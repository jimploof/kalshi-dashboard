FROM node:24-slim

# Run as the built-in 'node' user (uid 1000) so that any files the container
# writes into the bind-mounted workspace appear as the host user, not root.
# In WSL2 Ubuntu the default user is also uid 1000, so ownership matches.
WORKDIR /app
RUN chown node:node /app

USER node

COPY --chown=node:node package.json ./

# Install deps as node user so the anonymous volume is owned by node too
RUN npm install

COPY --chown=node:node . .

EXPOSE 4200

# proxy.conf.json is wired into angular.json; ng serve picks it up automatically
CMD ["npx", "ng", "serve", "--host", "0.0.0.0", "--port", "4200", "--poll", "2000"]
