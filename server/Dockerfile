FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci --omit=dev

COPY server/ ./server/
COPY index.html ./
COPY journey_data.js ./
COPY *.jpg ./
COPY mobile/ ./mobile/

ENV PORT=4000 \
    HOST=0.0.0.0

EXPOSE 4000

CMD ["node", "server/index.js"]
