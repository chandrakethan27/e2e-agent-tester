FROM node:22-alpine
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1 NODE_ENV=production
COPY package.json ./
RUN npm install --include=dev --no-audit --no-fund
COPY . .
RUN npm run build
USER node
EXPOSE 3000
CMD ["npm", "start"]
