FROM node:20-bookworm-slim AS dev

WORKDIR /app
ENV npm_config_update_notifier=false \
    npm_config_loglevel=error

COPY package*.json ./
RUN npm install --no-audit --no-fund --no-progress --loglevel=error

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]

FROM node:20-bookworm-slim AS build

WORKDIR /app
ENV npm_config_update_notifier=false \
    npm_config_loglevel=error

COPY package*.json ./
RUN npm ci --no-audit --no-fund --no-progress --loglevel=error

COPY . .

RUN npm run build -- --logLevel error

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY docker/nginx-root.conf /etc/nginx/nginx.conf
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/env.template.js /usr/share/nginx/html/env.template.js

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1

CMD ["/bin/sh", "-c", "envsubst < /usr/share/nginx/html/env.template.js > /usr/share/nginx/html/env.js && nginx -g 'daemon off;'"]
