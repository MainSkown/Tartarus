FROM node:26-alpine@sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797 AS dependencies
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

FROM nginx:1.31.8-alpine3.24@sha256:1ef7ca94d7879df82421428ce13bd1eaa412404953859cf7a5b6512c25e67a60 AS production-stage
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build-stage /app/dist/pwa /usr/share/nginx/html
RUN nginx -t
EXPOSE 80
