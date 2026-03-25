FROM node:24-slim

WORKDIR /app

COPY package.json ./

# npm install resolves and installs all deps (no lockfile required for initial build)
RUN npm install

COPY . .

EXPOSE 4200

# proxy.conf.json is wired into angular.json; ng serve picks it up automatically
CMD ["npx", "ng", "serve", "--host", "0.0.0.0", "--port", "4200", "--poll", "2000"]
