FROM node:22-alpine

WORKDIR /app

COPY frontend/package*.json /app/frontend/
RUN npm --prefix frontend ci

COPY frontend /app/frontend

WORKDIR /app/frontend
EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
