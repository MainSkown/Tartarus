FROM node:24-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
# Lifecycle scripts are skipped: the only one in the tree is an optional native fallback
# (@parcel/watcher) that would need a compiler toolchain on Alpine.
RUN npm ci --ignore-scripts
# Quasar's PWA mode keeps its service-worker dependencies in a separate package.
COPY src-pwa/package.json src-pwa/package-lock.json ./src-pwa/
RUN npm ci --ignore-scripts --prefix src-pwa

FROM dependencies AS dev-stage
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]

FROM dependencies AS build-stage
COPY . .
RUN npm run build

FROM nginx:alpine AS production-stage
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build-stage /app/dist/pwa /usr/share/nginx/html
RUN nginx -t
EXPOSE 80
