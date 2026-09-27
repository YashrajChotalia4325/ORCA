FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY scripts ./scripts
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_ORCA_API=http://localhost:8000
ENV NEXT_PUBLIC_ORCA_API=$NEXT_PUBLIC_ORCA_API
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app ./
EXPOSE 3000
CMD ["npm", "run", "start"]
