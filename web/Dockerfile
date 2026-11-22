FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx-https.conf /etc/nginx/https.conf
COPY docker-entrypoint.sh /opt/machi-entrypoint.sh
RUN chmod +x /opt/machi-entrypoint.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 5173 5174
ENTRYPOINT ["/opt/machi-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]